from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from enum import StrEnum

from forex_trader.domain.enums import Direction
from forex_trader.domain.models import Candle


class SwingKind(StrEnum):
    HIGH = "high"
    LOW = "low"


@dataclass(frozen=True, slots=True)
class SwingPoint:
    index: int
    kind: SwingKind
    price: Decimal
    time: object


@dataclass(frozen=True, slots=True)
class StructureState:
    direction: Direction
    swings: tuple[SwingPoint, ...]
    last_high: SwingPoint | None
    last_low: SwingPoint | None
    prior_high: SwingPoint | None
    prior_low: SwingPoint | None
    bos_up: bool
    bos_down: bool
    mss_up: bool
    mss_down: bool

    @property
    def shifted(self) -> bool:
        return self.mss_up or self.mss_down or self.bos_up or self.bos_down


def find_swings(
    candles: list[Candle],
    *,
    left: int = 2,
    right: int = 2,
) -> list[SwingPoint]:
    """Return confirmed pivots only; the right-hand confirmation bars prevent look-ahead."""
    if left < 1 or right < 1:
        raise ValueError("left/right pivot widths must be positive")
    if len(candles) < left + right + 1:
        return []
    points: list[SwingPoint] = []
    for index in range(left, len(candles) - right):
        candle = candles[index]
        left_slice = candles[index - left : index]
        right_slice = candles[index + 1 : index + right + 1]
        if all(candle.high > other.high for other in (*left_slice, *right_slice)):
            points.append(SwingPoint(index, SwingKind.HIGH, candle.high, candle.time))
        if all(candle.low < other.low for other in (*left_slice, *right_slice)):
            points.append(SwingPoint(index, SwingKind.LOW, candle.low, candle.time))
    return points


def assess_structure(candles: list[Candle]) -> StructureState:
    completed = [candle for candle in candles if candle.complete]
    swings = find_swings(completed)
    highs = [point for point in swings if point.kind is SwingKind.HIGH]
    lows = [point for point in swings if point.kind is SwingKind.LOW]
    last_high = highs[-1] if highs else None
    prior_high = highs[-2] if len(highs) >= 2 else None
    last_low = lows[-1] if lows else None
    prior_low = lows[-2] if len(lows) >= 2 else None

    direction = Direction.FLAT
    if last_high and prior_high and last_low and prior_low:
        higher_high = last_high.price > prior_high.price
        higher_low = last_low.price > prior_low.price
        lower_high = last_high.price < prior_high.price
        lower_low = last_low.price < prior_low.price
        if higher_high and higher_low:
            direction = Direction.LONG
        elif lower_high and lower_low:
            direction = Direction.SHORT

    close = completed[-1].close if completed else Decimal("0")
    # A structural break is measured against an already-confirmed pivot, never a
    # pivot that needs the current candle or a future candle for confirmation.
    bos_up = bool(last_high and close > last_high.price)
    bos_down = bool(last_low and close < last_low.price)
    mss_up = direction is Direction.SHORT and bos_up
    mss_down = direction is Direction.LONG and bos_down
    return StructureState(
        direction=direction,
        swings=tuple(swings),
        last_high=last_high,
        last_low=last_low,
        prior_high=prior_high,
        prior_low=prior_low,
        bos_up=bos_up,
        bos_down=bos_down,
        mss_up=mss_up,
        mss_down=mss_down,
    )


def broke_level_after(
    candles: list[Candle],
    *,
    start_index: int,
    direction: Direction,
    reference: Decimal,
) -> bool:
    subsequent = candles[start_index + 1 :]
    if direction is Direction.LONG:
        return any(candle.close > reference for candle in subsequent)
    if direction is Direction.SHORT:
        return any(candle.close < reference for candle in subsequent)
    return False
