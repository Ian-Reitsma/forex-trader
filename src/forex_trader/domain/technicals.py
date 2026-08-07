from __future__ import annotations

from decimal import Decimal

from forex_trader.domain.enums import Direction
from forex_trader.domain.models import Candle, TechnicalAssessment


def _require(values: list[Decimal], period: int) -> None:
    if len(values) < period:
        raise ValueError(f"need at least {period} values")


def ema(values: list[Decimal], period: int) -> Decimal:
    _require(values, period)
    alpha = Decimal("2") / Decimal(period + 1)
    result = sum(values[:period]) / Decimal(period)
    for value in values[period:]:
        result = value * alpha + result * (Decimal("1") - alpha)
    return result


def atr(candles: list[Candle], period: int = 14) -> Decimal:
    if len(candles) < period + 1:
        raise ValueError(f"need at least {period + 1} candles")
    ranges: list[Decimal] = []
    for previous, current in zip(candles[-period - 1 : -1], candles[-period:], strict=True):
        ranges.append(
            max(
                current.high - current.low,
                abs(current.high - previous.close),
                abs(current.low - previous.close),
            )
        )
    return sum(ranges) / Decimal(period)


def rsi(values: list[Decimal], period: int = 14) -> Decimal:
    if len(values) < period + 1:
        raise ValueError(f"need at least {period + 1} values")
    deltas = [b - a for a, b in zip(values[-period - 1 : -1], values[-period:], strict=True)]
    gains = sum((d for d in deltas if d > 0), Decimal("0")) / Decimal(period)
    losses = sum((-d for d in deltas if d < 0), Decimal("0")) / Decimal(period)
    if losses == 0:
        return Decimal("100")
    relative_strength = gains / losses
    return Decimal("100") - Decimal("100") / (Decimal("1") + relative_strength)


def pip_size(instrument: str) -> Decimal:
    return Decimal("0.01") if instrument.endswith("_JPY") else Decimal("0.0001")


def assess_technicals(
    instrument: str,
    lower: list[Candle],
    higher: list[Candle],
    *,
    reward_risk: Decimal = Decimal("2"),
) -> TechnicalAssessment:
    """Build a conservative multi-timeframe scalp assessment.

    The function identifies direction from H1 structure, but marks a setup as high-quality
    only when the latest completed M5 candle also sweeps liquidity and displaces back in
    the trend direction. The fusion policy decides whether those confirmations are mandatory.
    """
    completed_lower = [c for c in lower if c.complete]
    completed_higher = [c for c in higher if c.complete]
    if len(completed_lower) < 60 or len(completed_higher) < 60:
        raise ValueError("at least 60 completed candles are required per timeframe")
    if reward_risk <= Decimal("1"):
        raise ValueError("reward_risk must be greater than 1")

    lower_closes = [c.close for c in completed_lower]
    higher_closes = [c.close for c in completed_higher]
    current = completed_lower[-1]
    current_atr = atr(completed_lower)
    higher_atr = atr(completed_higher)
    current_rsi = rsi(lower_closes)

    h_fast = ema(higher_closes, 20)
    h_slow = ema(higher_closes, 50)
    l_fast = ema(lower_closes, 9)
    l_slow = ema(lower_closes, 21)

    long_trend = h_fast > h_slow and higher_closes[-1] > h_fast
    short_trend = h_fast < h_slow and higher_closes[-1] < h_fast
    trend_strength = abs(h_fast - h_slow) / max(higher_atr, pip_size(instrument))

    lookback = completed_lower[-11:-1]
    prior_low = min(c.low for c in lookback)
    prior_high = max(c.high for c in lookback)
    long_sweep = current.low < prior_low and current.close > prior_low
    short_sweep = current.high > prior_high and current.close < prior_high

    bodies = [abs(c.close - c.open) for c in completed_lower[-11:-1]]
    average_body = sum(bodies) / Decimal(len(bodies))
    current_body = abs(current.close - current.open)
    current_range = max(current.high - current.low, pip_size(instrument))
    close_location = (current.close - current.low) / current_range
    displacement = current_body >= max(
        current_atr * Decimal("0.45"), average_body * Decimal("1.25")
    )

    reasons: list[str] = []
    score = Decimal("0")
    direction = Direction.FLAT
    confirmed_sweep = False
    directional_displacement = False

    if long_trend:
        direction = Direction.LONG
        score += Decimal("0.25")
        reasons.append("higher-timeframe EMA structure is bullish")
        if trend_strength >= Decimal("0.12"):
            score += Decimal("0.10")
            reasons.append(f"higher-timeframe trend strength={trend_strength:.3f}")
        if l_fast >= l_slow:
            score += Decimal("0.15")
            reasons.append("lower-timeframe momentum is bullish")
        if long_sweep:
            confirmed_sweep = True
            score += Decimal("0.25")
            reasons.append("sell-side liquidity was swept and reclaimed")
        directional_displacement = displacement and current.close > current.open and close_location >= Decimal("0.62")
        if directional_displacement:
            score += Decimal("0.15")
            reasons.append("bullish displacement closes in the upper candle range")
        if Decimal("38") <= current_rsi <= Decimal("67"):
            score += Decimal("0.10")
            reasons.append("RSI is compatible with bullish continuation")
    elif short_trend:
        direction = Direction.SHORT
        score += Decimal("0.25")
        reasons.append("higher-timeframe EMA structure is bearish")
        if trend_strength >= Decimal("0.12"):
            score += Decimal("0.10")
            reasons.append(f"higher-timeframe trend strength={trend_strength:.3f}")
        if l_fast <= l_slow:
            score += Decimal("0.15")
            reasons.append("lower-timeframe momentum is bearish")
        if short_sweep:
            confirmed_sweep = True
            score += Decimal("0.25")
            reasons.append("buy-side liquidity was swept and rejected")
        directional_displacement = displacement and current.close < current.open and close_location <= Decimal("0.38")
        if directional_displacement:
            score += Decimal("0.15")
            reasons.append("bearish displacement closes in the lower candle range")
        if Decimal("33") <= current_rsi <= Decimal("62"):
            score += Decimal("0.10")
            reasons.append("RSI is compatible with bearish continuation")
    else:
        reasons.append("higher-timeframe structure is not directional")

    if direction is Direction.LONG:
        stop = min(c.low for c in completed_lower[-8:]) - current_atr * Decimal("0.10")
        risk = current.close - stop
        take = current.close + risk * reward_risk
    elif direction is Direction.SHORT:
        stop = max(c.high for c in completed_lower[-8:]) + current_atr * Decimal("0.10")
        risk = stop - current.close
        take = current.close - risk * reward_risk
    else:
        stop = None
        take = None

    return TechnicalAssessment(
        instrument=instrument,
        direction=direction,
        score=min(Decimal("1"), score),
        atr=current_atr,
        rsi=current_rsi,
        entry_reference=current.close,
        stop_reference=stop,
        take_profit_reference=take,
        reasons=tuple(reasons),
        signal_time=current.time,
        liquidity_sweep=confirmed_sweep,
        displacement=directional_displacement,
        trend_strength=trend_strength,
        reward_risk=reward_risk if direction is not Direction.FLAT else Decimal("0"),
    )
