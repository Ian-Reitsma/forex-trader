from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from forex_trader.domain.enums import Direction
from forex_trader.domain.models import Candle


@dataclass(frozen=True, slots=True)
class OrderFlowEvidence:
    source_kind: str
    directional_pressure: Decimal
    vwap: Decimal | None
    relative_activity: Decimal
    direction: Direction
    confidence: Decimal
    reasons: tuple[str, ...]


def broker_tick_activity_proxy(candles: list[Candle], *, window: int = 24) -> OrderFlowEvidence:
    """Use broker candle tick counts only as a local activity proxy.

    This deliberately does not call tick volume institutional order flow. It is a
    fallback feature until an executed bid/ask futures or venue feed is connected.
    """
    completed = [candle for candle in candles if candle.complete]
    if len(completed) < max(8, window):
        return OrderFlowEvidence(
            source_kind="broker_tick_proxy",
            directional_pressure=Decimal("0"),
            vwap=None,
            relative_activity=Decimal("0"),
            direction=Direction.FLAT,
            confidence=Decimal("0"),
            reasons=("insufficient broker tick history",),
        )
    sample = completed[-window:]
    total_volume = sum((Decimal(max(candle.volume, 0)) for candle in sample), Decimal("0"))
    if total_volume <= 0:
        return OrderFlowEvidence(
            source_kind="broker_tick_proxy",
            directional_pressure=Decimal("0"),
            vwap=None,
            relative_activity=Decimal("0"),
            direction=Direction.FLAT,
            confidence=Decimal("0"),
            reasons=("broker did not provide usable tick counts",),
        )
    weighted_price = sum(
        (((candle.high + candle.low + candle.close) / Decimal("3")) * Decimal(candle.volume) for candle in sample),
        Decimal("0"),
    )
    signed = sum(
        (
            Decimal(candle.volume)
            * (Decimal("1") if candle.close > candle.open else Decimal("-1") if candle.close < candle.open else Decimal("0"))
            for candle in sample
        ),
        Decimal("0"),
    )
    pressure = max(Decimal("-1"), min(Decimal("1"), signed / total_volume))
    baseline = sum((Decimal(candle.volume) for candle in sample[:-1]), Decimal("0")) / Decimal(len(sample) - 1)
    relative = Decimal("0") if baseline <= 0 else Decimal(sample[-1].volume) / baseline
    direction = Direction.LONG if pressure >= Decimal("0.20") else Direction.SHORT if pressure <= Decimal("-0.20") else Direction.FLAT
    confidence = min(Decimal("0.35"), abs(pressure) * Decimal("0.35"))
    return OrderFlowEvidence(
        source_kind="broker_tick_proxy",
        directional_pressure=pressure,
        vwap=weighted_price / total_volume,
        relative_activity=relative,
        direction=direction,
        confidence=confidence,
        reasons=(
            "broker tick counts are a local activity proxy, not centralized institutional volume",
            f"tick-pressure={pressure:.3f}",
            f"relative-activity={relative:.2f}",
        ),
    )
