from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from forex_trader.domain.models import Candle, FundamentalAssessment, Quote


@dataclass(frozen=True, slots=True)
class SignalEvaluationInputs:
    """Exact point-in-time inputs consumed by one production signal decision.

    The capture deliberately stops before portfolio risk and execution. It exists so research
    can rerun component ablations on the same decision-time candles, quote, fundamental
    assessment, adaptive spread ceiling and context gates without issuing another provider
    request or mutating broker state.
    """

    instrument: str
    lower_candles: tuple[Candle, ...]
    higher_candles: tuple[Candle, ...]
    quote: Quote
    fundamental: FundamentalAssessment
    maximum_spread_pips: Decimal
    event_blackout_reasons: tuple[str, ...] = ()
    rollover_blackout: bool = False

    def __post_init__(self) -> None:
        normalized = self.instrument.strip().upper()
        if not normalized:
            raise ValueError("signal capture instrument is required")
        if self.quote.instrument.upper() != normalized:
            raise ValueError("signal capture quote instrument does not match")
        if self.fundamental.instrument.upper() != normalized:
            raise ValueError("signal capture fundamental instrument does not match")
        if not self.lower_candles or not self.higher_candles:
            raise ValueError("signal capture requires lower and higher candles")
        if self.maximum_spread_pips <= 0:
            raise ValueError("signal capture maximum_spread_pips must be positive")
