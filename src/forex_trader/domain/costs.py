from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from enum import StrEnum
from statistics import median

from forex_trader.domain.models import Quote
from forex_trader.domain.technicals import pip_size


class TradingSession(StrEnum):
    ASIA = "asia"
    LONDON = "london"
    LONDON_NEW_YORK = "london_new_york_overlap"
    NEW_YORK = "new_york"
    OFF_HOURS = "off_hours"


def trading_session(timestamp: datetime) -> TradingSession:
    if timestamp.tzinfo is None:
        raise ValueError("timestamp must be timezone-aware")
    hour = timestamp.astimezone(UTC).hour
    # UTC session map. Boundaries deliberately overlap only where liquidity does.
    if 7 <= hour < 12:
        return TradingSession.LONDON
    if 12 <= hour < 16:
        return TradingSession.LONDON_NEW_YORK
    if 16 <= hour < 21:
        return TradingSession.NEW_YORK
    if 0 <= hour < 7:
        return TradingSession.ASIA
    return TradingSession.OFF_HOURS


@dataclass(frozen=True, slots=True)
class CostSample:
    instrument: str
    observed_at: datetime
    session: TradingSession
    spread_pips: Decimal
    slippage_pips: Decimal | None = None
    event_risk: bool = False


@dataclass(frozen=True, slots=True)
class CostProfile:
    instrument: str
    session: TradingSession
    sample_count: int
    median_spread_pips: Decimal
    p90_spread_pips: Decimal
    p95_spread_pips: Decimal
    median_slippage_pips: Decimal | None
    p90_slippage_pips: Decimal | None


class SessionCostModel:
    """Learns execution costs without allowing the model to widen risk indefinitely."""

    def __init__(self, samples: list[CostSample] | None = None, *, minimum_samples: int = 30) -> None:
        if minimum_samples < 1:
            raise ValueError("minimum_samples must be positive")
        self.minimum_samples = minimum_samples
        self._samples = list(samples or [])

    def record_quote(self, quote: Quote, *, event_risk: bool = False) -> CostSample:
        sample = CostSample(
            instrument=quote.instrument.upper(),
            observed_at=quote.time,
            session=trading_session(quote.time),
            spread_pips=quote.spread / pip_size(quote.instrument),
            event_risk=event_risk,
        )
        self._samples.append(sample)
        return sample

    def record_slippage(
        self,
        *,
        instrument: str,
        observed_at: datetime,
        intended_price: Decimal,
        fill_price: Decimal,
        event_risk: bool = False,
    ) -> CostSample:
        if intended_price <= 0 or fill_price <= 0:
            raise ValueError("prices must be positive")
        slippage = abs(fill_price - intended_price) / pip_size(instrument)
        sample = CostSample(
            instrument=instrument.upper(),
            observed_at=observed_at,
            session=trading_session(observed_at),
            spread_pips=Decimal("0"),
            slippage_pips=slippage,
            event_risk=event_risk,
        )
        self._samples.append(sample)
        return sample

    def profile(self, instrument: str, timestamp: datetime) -> CostProfile | None:
        session = trading_session(timestamp)
        matches = [
            sample
            for sample in self._samples
            if sample.instrument == instrument.upper()
            and sample.session is session
            and not sample.event_risk
            and sample.spread_pips > 0
        ]
        if len(matches) < self.minimum_samples:
            return None
        spreads = sorted(sample.spread_pips for sample in matches)
        slippages = sorted(
            sample.slippage_pips for sample in matches if sample.slippage_pips is not None
        )
        return CostProfile(
            instrument=instrument.upper(),
            session=session,
            sample_count=len(matches),
            median_spread_pips=Decimal(str(median(spreads))),
            p90_spread_pips=_percentile(spreads, Decimal("0.90")),
            p95_spread_pips=_percentile(spreads, Decimal("0.95")),
            median_slippage_pips=(
                Decimal(str(median(slippages))) if slippages else None
            ),
            p90_slippage_pips=(
                _percentile(slippages, Decimal("0.90")) if slippages else None
            ),
        )

    def spread_limit(
        self,
        instrument: str,
        timestamp: datetime,
        *,
        configured_maximum: Decimal,
    ) -> Decimal:
        if configured_maximum <= 0:
            raise ValueError("configured_maximum must be positive")
        profile = self.profile(instrument, timestamp)
        if profile is None:
            return configured_maximum
        # Never let learned costs loosen the configured hard ceiling. The learned
        # threshold can only make the engine more selective in an expensive session.
        learned = max(profile.median_spread_pips * Decimal("1.5"), profile.p90_spread_pips)
        return min(configured_maximum, learned)

    def samples(self) -> list[CostSample]:
        return list(self._samples)


def _percentile(values: list[Decimal], fraction: Decimal) -> Decimal:
    if not values:
        raise ValueError("percentile requires at least one value")
    if not Decimal("0") <= fraction <= Decimal("1"):
        raise ValueError("fraction must be between 0 and 1")
    index = int((Decimal(len(values) - 1) * fraction).to_integral_value(rounding="ROUND_HALF_UP"))
    return values[index]
