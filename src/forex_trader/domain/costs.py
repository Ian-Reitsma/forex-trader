from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from statistics import median

from forex_trader.domain.instruments import pip_size_for
from forex_trader.domain.models import Quote
from forex_trader.domain.sessions import TradingSession, classify_session

# Backward-compatible function name used by existing callers/tests.
trading_session = classify_session


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
    spread_sample_count: int
    slippage_sample_count: int
    median_spread_pips: Decimal | None
    p90_spread_pips: Decimal | None
    p95_spread_pips: Decimal | None
    median_slippage_pips: Decimal | None
    p90_slippage_pips: Decimal | None


class SessionCostModel:
    """Learn spread and signed execution slippage by DST-aware session.

    Learned thresholds can tighten a configured hard ceiling but can never widen it.
    """

    def __init__(self, samples: list[CostSample] | None = None, *, minimum_samples: int = 30) -> None:
        if minimum_samples < 1:
            raise ValueError("minimum_samples must be positive")
        self.minimum_samples = minimum_samples
        self._samples = list(samples or [])

    def record_quote(self, quote: Quote, *, event_risk: bool = False) -> CostSample:
        sample = CostSample(
            instrument=quote.instrument.upper(),
            observed_at=quote.time,
            session=classify_session(quote.time),
            spread_pips=quote.spread / pip_size_for(quote.instrument),
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
        direction: str | None = None,
        event_risk: bool = False,
    ) -> CostSample:
        if intended_price <= 0 or fill_price <= 0:
            raise ValueError("prices must be positive")
        raw = (fill_price - intended_price) / pip_size_for(instrument)
        # Positive means adverse execution, negative means price improvement.
        if direction == "short":
            raw = -raw
        sample = CostSample(
            instrument=instrument.upper(),
            observed_at=observed_at,
            session=classify_session(observed_at),
            spread_pips=Decimal("0"),
            slippage_pips=raw,
            event_risk=event_risk,
        )
        self._samples.append(sample)
        return sample

    def profile(self, instrument: str, timestamp: datetime) -> CostProfile | None:
        session = classify_session(timestamp)
        common = [
            sample
            for sample in self._samples
            if sample.instrument == instrument.upper()
            and sample.session is session
            and not sample.event_risk
        ]
        spread_samples = [sample.spread_pips for sample in common if sample.spread_pips > 0]
        slippage_samples = [sample.slippage_pips for sample in common if sample.slippage_pips is not None]
        if len(spread_samples) < self.minimum_samples and len(slippage_samples) < self.minimum_samples:
            return None
        spreads = sorted(spread_samples)
        slippages = sorted(slippage_samples)
        return CostProfile(
            instrument=instrument.upper(),
            session=session,
            sample_count=len(common),
            spread_sample_count=len(spreads),
            slippage_sample_count=len(slippages),
            median_spread_pips=Decimal(str(median(spreads))) if spreads else None,
            p90_spread_pips=_percentile(spreads, Decimal("0.90")) if spreads else None,
            p95_spread_pips=_percentile(spreads, Decimal("0.95")) if spreads else None,
            median_slippage_pips=Decimal(str(median(slippages))) if slippages else None,
            p90_slippage_pips=_percentile(slippages, Decimal("0.90")) if slippages else None,
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
        if profile is None or profile.median_spread_pips is None or profile.p90_spread_pips is None:
            return configured_maximum
        learned = max(profile.median_spread_pips * Decimal("1.5"), profile.p90_spread_pips)
        return min(configured_maximum, learned)

    def slippage_allowance(
        self,
        instrument: str,
        timestamp: datetime,
        *,
        configured_maximum: Decimal,
    ) -> Decimal:
        if configured_maximum <= 0:
            raise ValueError("configured_maximum must be positive")
        profile = self.profile(instrument, timestamp)
        if profile is None or profile.p90_slippage_pips is None:
            return configured_maximum
        adverse = max(Decimal("0"), profile.p90_slippage_pips)
        return min(configured_maximum, max(Decimal("0.1"), adverse))

    def samples(self) -> list[CostSample]:
        return list(self._samples)


def _percentile(values: list[Decimal], fraction: Decimal) -> Decimal:
    if not values:
        raise ValueError("percentile requires at least one value")
    if not Decimal("0") <= fraction <= Decimal("1"):
        raise ValueError("fraction must be between 0 and 1")
    index = int((Decimal(len(values) - 1) * fraction).to_integral_value(rounding="ROUND_HALF_UP"))
    return values[index]
