from __future__ import annotations

from datetime import timedelta
from decimal import Decimal
from typing import Callable

from forex_trader.domain.fundamentals import FundamentalBook
from forex_trader.domain.macro_history import PointInTimeFundamentalBook
from forex_trader.domain.models import Candle, Quote, TradeCandidate
from forex_trader.domain.strategy import SignalFusionPolicy
from forex_trader.domain.technicals import assess_technicals, pip_size


SpreadModel = Callable[[Candle, int], Decimal]


def prepare_walk_forward_data(
    lower_candles: list[Candle],
    higher_candles: list[Candle],
) -> tuple[list[Candle], list[Candle]]:
    lower = sorted((c for c in lower_candles if c.complete), key=lambda candle: candle.time)
    higher = sorted((c for c in higher_candles if c.complete), key=lambda candle: candle.time)
    if len(lower) < 82 or len(higher) < 60:
        raise ValueError("walk-forward research requires at least 82 lower and 60 higher candles")
    return lower, higher


def build_walk_forward_candidate(
    *,
    instrument: str,
    lower: list[Candle],
    higher: list[Candle],
    index: int,
    fundamentals: FundamentalBook | PointInTimeFundamentalBook,
    fusion_policy: SignalFusionPolicy,
    spread_pips: Decimal = Decimal("1.0"),
    spread_model: SpreadModel | None = None,
    lower_timeframe: timedelta = timedelta(minutes=5),
    higher_timeframe: timedelta = timedelta(hours=1),
) -> TradeCandidate | None:
    """Construct exactly one no-lookahead candidate at a walk-forward index.

    Returns `None` when the higher-timeframe completion set is not yet large enough.
    This helper is shared by management research so exit-policy comparisons cannot
    silently use a different signal timestamp, spread, macro snapshot, or HTF cutoff.
    """
    if not 0 <= index < len(lower):
        raise IndexError("walk-forward index is outside lower-candle history")
    if spread_pips < 0:
        raise ValueError("spread_pips cannot be negative")
    if lower_timeframe <= timedelta(0) or higher_timeframe <= timedelta(0):
        raise ValueError("timeframe durations must be positive")
    signal_candle = lower[index]
    decision_time = signal_candle.time + lower_timeframe
    higher_available = [
        candle
        for candle in higher
        if candle.time + higher_timeframe <= decision_time
    ]
    if len(higher_available) < 60:
        return None
    technical = assess_technicals(
        instrument,
        lower[max(0, index - 199) : index + 1],
        higher_available[-200:],
    )
    decision_spread = spread_for(signal_candle, index, spread_pips, spread_model)
    half_spread = pip_size(instrument) * decision_spread / Decimal("2")
    quote = Quote(
        instrument=instrument,
        bid=signal_candle.close - half_spread,
        ask=signal_candle.close + half_spread,
        time=decision_time + timedelta(seconds=1),
    )
    fundamental = fundamentals.assess_pair(instrument, as_of=quote.time)
    return fusion_policy.evaluate(technical, fundamental, quote)


def spread_for(
    candle: Candle,
    index: int,
    fallback: Decimal,
    model: SpreadModel | None,
) -> Decimal:
    value = fallback if model is None else model(candle, index)
    value = Decimal(str(value))
    if value < 0:
        raise ValueError("spread model cannot return a negative spread")
    return value
