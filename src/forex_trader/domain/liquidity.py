from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC
from decimal import Decimal
from enum import StrEnum

from forex_trader.domain.enums import Direction
from forex_trader.domain.market_structure import SwingKind, find_swings
from forex_trader.domain.models import Candle


class LiquidityKind(StrEnum):
    PRIOR_DAY_HIGH = "prior_day_high"
    PRIOR_DAY_LOW = "prior_day_low"
    EQUAL_HIGHS = "equal_highs"
    EQUAL_LOWS = "equal_lows"
    EXTERNAL_SWING_HIGH = "external_swing_high"
    EXTERNAL_SWING_LOW = "external_swing_low"
    ROUND_NUMBER = "round_number"


@dataclass(frozen=True, slots=True)
class LiquidityLevel:
    kind: LiquidityKind
    price: Decimal
    strength: Decimal
    source_time: object | None = None


@dataclass(frozen=True, slots=True)
class SweepEvent:
    direction: Direction
    level: LiquidityLevel
    candle_index: int
    extreme: Decimal
    reclaim_close: Decimal
    excursion: Decimal


def build_liquidity_map(
    candles: list[Candle],
    *,
    pip_size: Decimal,
) -> list[LiquidityLevel]:
    completed = [candle for candle in candles if candle.complete]
    if len(completed) < 12:
        return []
    levels: list[LiquidityLevel] = []
    levels.extend(_prior_day_levels(completed))
    swings = find_swings(completed, left=2, right=2)
    highs = [point for point in swings if point.kind is SwingKind.HIGH]
    lows = [point for point in swings if point.kind is SwingKind.LOW]
    if highs:
        levels.append(LiquidityLevel(LiquidityKind.EXTERNAL_SWING_HIGH, highs[-1].price, Decimal("0.70"), highs[-1].time))
    if lows:
        levels.append(LiquidityLevel(LiquidityKind.EXTERNAL_SWING_LOW, lows[-1].price, Decimal("0.70"), lows[-1].time))
    levels.extend(_equal_levels(highs, LiquidityKind.EQUAL_HIGHS, tolerance=pip_size * Decimal("2.5")))
    levels.extend(_equal_levels(lows, LiquidityKind.EQUAL_LOWS, tolerance=pip_size * Decimal("2.5")))
    levels.extend(_round_levels(completed[-1].close, pip_size))
    return _deduplicate(levels, pip_size)


def find_recent_sweep(
    candles: list[Candle],
    levels: list[LiquidityLevel],
    *,
    pip_size: Decimal,
    max_bars: int = 8,
    minimum_excursion_pips: Decimal = Decimal("0.4"),
) -> SweepEvent | None:
    completed = [candle for candle in candles if candle.complete]
    if not completed or not levels:
        return None
    start = max(0, len(completed) - max_bars)
    best: SweepEvent | None = None
    for index in range(start, len(completed)):
        candle = completed[index]
        for level in levels:
            if level.kind in {LiquidityKind.PRIOR_DAY_LOW, LiquidityKind.EQUAL_LOWS, LiquidityKind.EXTERNAL_SWING_LOW, LiquidityKind.ROUND_NUMBER}:
                excursion = level.price - candle.low
                if excursion >= pip_size * minimum_excursion_pips and candle.close > level.price:
                    event = SweepEvent(Direction.LONG, level, index, candle.low, candle.close, excursion)
                    best = _prefer(best, event)
            if level.kind in {LiquidityKind.PRIOR_DAY_HIGH, LiquidityKind.EQUAL_HIGHS, LiquidityKind.EXTERNAL_SWING_HIGH, LiquidityKind.ROUND_NUMBER}:
                excursion = candle.high - level.price
                if excursion >= pip_size * minimum_excursion_pips and candle.close < level.price:
                    event = SweepEvent(Direction.SHORT, level, index, candle.high, candle.close, excursion)
                    best = _prefer(best, event)
    return best


def target_levels(
    levels: list[LiquidityLevel],
    *,
    direction: Direction,
    entry: Decimal,
) -> list[LiquidityLevel]:
    if direction is Direction.LONG:
        return sorted([level for level in levels if level.price > entry], key=lambda level: level.price)
    if direction is Direction.SHORT:
        return sorted([level for level in levels if level.price < entry], key=lambda level: level.price, reverse=True)
    return []


def _prior_day_levels(candles: list[Candle]) -> list[LiquidityLevel]:
    latest_day = candles[-1].time.astimezone(UTC).date()
    days = sorted({candle.time.astimezone(UTC).date() for candle in candles if candle.time.astimezone(UTC).date() < latest_day})
    if not days:
        return []
    prior_day = days[-1]
    prior = [candle for candle in candles if candle.time.astimezone(UTC).date() == prior_day]
    if not prior:
        return []
    return [
        LiquidityLevel(LiquidityKind.PRIOR_DAY_HIGH, max(c.high for c in prior), Decimal("1.0"), prior[-1].time),
        LiquidityLevel(LiquidityKind.PRIOR_DAY_LOW, min(c.low for c in prior), Decimal("1.0"), prior[-1].time),
    ]


def _equal_levels(points: list[object], kind: LiquidityKind, *, tolerance: Decimal) -> list[LiquidityLevel]:
    results: list[LiquidityLevel] = []
    for first, second in zip(points[-8:-1], points[-7:], strict=False):
        first_price = Decimal(str(getattr(first, "price")))
        second_price = Decimal(str(getattr(second, "price")))
        if abs(first_price - second_price) <= tolerance:
            results.append(
                LiquidityLevel(
                    kind,
                    (first_price + second_price) / Decimal("2"),
                    Decimal("0.85"),
                    getattr(second, "time", None),
                )
            )
    return results


def _round_levels(price: Decimal, pip_size: Decimal) -> list[LiquidityLevel]:
    # Major/half handles: for a standard 0.0001 pip pair this produces 50-pip
    # spacing; for 0.01 JPY-style pips it produces 50-pip spacing as well.
    spacing = pip_size * Decimal("50")
    if spacing <= 0:
        return []
    bucket = (price / spacing).to_integral_value()
    return [
        LiquidityLevel(LiquidityKind.ROUND_NUMBER, (bucket + offset) * spacing, Decimal("0.45"))
        for offset in (Decimal("-1"), Decimal("0"), Decimal("1"))
    ]


def _deduplicate(levels: list[LiquidityLevel], pip_size: Decimal) -> list[LiquidityLevel]:
    selected: list[LiquidityLevel] = []
    tolerance = pip_size * Decimal("0.5")
    for level in sorted(levels, key=lambda item: item.strength, reverse=True):
        if any(abs(level.price - other.price) <= tolerance and level.kind is other.kind for other in selected):
            continue
        selected.append(level)
    return selected


def _prefer(current: SweepEvent | None, candidate: SweepEvent) -> SweepEvent:
    if current is None:
        return candidate
    # Most recent sweep wins; stronger declared liquidity breaks same-bar ties.
    return candidate if (candidate.candle_index, candidate.level.strength) > (current.candle_index, current.level.strength) else current
