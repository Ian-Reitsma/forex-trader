from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal
from enum import StrEnum

from forex_trader.domain.enums import Direction
from forex_trader.domain.market_structure import SwingKind, find_swings
from forex_trader.domain.models import Candle
from forex_trader.domain.risk_day import (
    fx_bar_risk_day_key,
    fx_bar_week_key,
    fx_risk_day_key,
    fx_week_key,
)
from forex_trader.domain.sessions import LONDON, NEW_YORK, TOKYO, SessionDefinition


class LiquidityKind(StrEnum):
    PRIOR_DAY_HIGH = "prior_day_high"
    PRIOR_DAY_LOW = "prior_day_low"
    PRIOR_WEEK_HIGH = "prior_week_high"
    PRIOR_WEEK_LOW = "prior_week_low"
    ASIA_HIGH = "asia_high"
    ASIA_LOW = "asia_low"
    LONDON_OPEN_HIGH = "london_open_high"
    LONDON_OPEN_LOW = "london_open_low"
    NEW_YORK_OPEN_HIGH = "new_york_open_high"
    NEW_YORK_OPEN_LOW = "new_york_open_low"
    EQUAL_HIGHS = "equal_highs"
    EQUAL_LOWS = "equal_lows"
    EXTERNAL_SWING_HIGH = "external_swing_high"
    EXTERNAL_SWING_LOW = "external_swing_low"
    ROUND_NUMBER = "round_number"


_LOW_KINDS = {
    LiquidityKind.PRIOR_DAY_LOW,
    LiquidityKind.PRIOR_WEEK_LOW,
    LiquidityKind.ASIA_LOW,
    LiquidityKind.LONDON_OPEN_LOW,
    LiquidityKind.NEW_YORK_OPEN_LOW,
    LiquidityKind.EQUAL_LOWS,
    LiquidityKind.EXTERNAL_SWING_LOW,
    LiquidityKind.ROUND_NUMBER,
}
_HIGH_KINDS = {
    LiquidityKind.PRIOR_DAY_HIGH,
    LiquidityKind.PRIOR_WEEK_HIGH,
    LiquidityKind.ASIA_HIGH,
    LiquidityKind.LONDON_OPEN_HIGH,
    LiquidityKind.NEW_YORK_OPEN_HIGH,
    LiquidityKind.EQUAL_HIGHS,
    LiquidityKind.EXTERNAL_SWING_HIGH,
    LiquidityKind.ROUND_NUMBER,
}


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
    context_candles: list[Candle] | None = None,
) -> list[LiquidityLevel]:
    """Build declared liquidity from completed price/session structure.

    Lower-timeframe history supplies the active 5-p.m.-New-York FX day, finalized session
    ranges, swings, equal highs/lows and handles. Optional higher-timeframe context supplies
    the previous completed Sunday-5-p.m. FX week. Session/opening-range levels are not
    emitted until their defining window is complete, preventing a moving partial range from
    masquerading as settled liquidity.
    """
    completed = [candle for candle in candles if candle.complete]
    if len(completed) < 12:
        return []
    step = _bar_step(completed)
    signal_time = completed[-1].time + step
    levels: list[LiquidityLevel] = []
    levels.extend(_prior_day_levels(completed, signal_time=signal_time, step=step))
    levels.extend(
        _completed_session_levels(
            completed,
            signal_time=signal_time,
            definition=TOKYO,
            high_kind=LiquidityKind.ASIA_HIGH,
            low_kind=LiquidityKind.ASIA_LOW,
            strength=Decimal("0.88"),
        )
    )
    levels.extend(
        _opening_range_levels(
            completed,
            signal_time=signal_time,
            definition=LONDON,
            high_kind=LiquidityKind.LONDON_OPEN_HIGH,
            low_kind=LiquidityKind.LONDON_OPEN_LOW,
            strength=Decimal("0.82"),
        )
    )
    levels.extend(
        _opening_range_levels(
            completed,
            signal_time=signal_time,
            definition=NEW_YORK,
            high_kind=LiquidityKind.NEW_YORK_OPEN_HIGH,
            low_kind=LiquidityKind.NEW_YORK_OPEN_LOW,
            strength=Decimal("0.82"),
        )
    )
    if context_candles:
        levels.extend(_prior_week_levels(context_candles, signal_time=signal_time))
    swings = find_swings(completed, left=2, right=2)
    highs = [point for point in swings if point.kind is SwingKind.HIGH]
    lows = [point for point in swings if point.kind is SwingKind.LOW]
    levels.extend(_recent_external_swings(highs, LiquidityKind.EXTERNAL_SWING_HIGH))
    levels.extend(_recent_external_swings(lows, LiquidityKind.EXTERNAL_SWING_LOW))
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
            # A swing/session level cannot be swept by the same candle that creates it.
            if level.source_time is not None and getattr(level.source_time, "__gt__", None) is not None:
                try:
                    if level.source_time >= candle.time:
                        continue
                except TypeError:
                    pass
            if level.kind in _LOW_KINDS:
                excursion = level.price - candle.low
                if excursion >= pip_size * minimum_excursion_pips and candle.close > level.price:
                    event = SweepEvent(Direction.LONG, level, index, candle.low, candle.close, excursion)
                    best = _prefer(best, event)
            if level.kind in _HIGH_KINDS:
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


def _bar_step(candles: list[Candle]) -> timedelta:
    if len(candles) < 2:
        raise ValueError("at least two candles are required to infer bar duration")
    step = candles[-1].time - candles[-2].time
    if step <= timedelta(0):
        raise ValueError("liquidity candles must have increasing timestamps")
    return step


def _prior_day_levels(
    candles: list[Candle],
    *,
    signal_time: datetime,
    step: timedelta,
) -> list[LiquidityLevel]:
    current_key = fx_risk_day_key(signal_time)
    groups: dict[str, list[Candle]] = defaultdict(list)
    for candle in candles:
        groups[fx_bar_risk_day_key(candle.time, step)].append(candle)
    prior_keys = sorted(key for key in groups if key < current_key)
    if not prior_keys:
        return []
    prior = groups[prior_keys[-1]]
    return [
        LiquidityLevel(LiquidityKind.PRIOR_DAY_HIGH, max(c.high for c in prior), Decimal("1.0"), prior[-1].time),
        LiquidityLevel(LiquidityKind.PRIOR_DAY_LOW, min(c.low for c in prior), Decimal("1.0"), prior[-1].time),
    ]


def _prior_week_levels(candles: list[Candle], *, signal_time: datetime) -> list[LiquidityLevel]:
    completed = [candle for candle in candles if candle.complete]
    if len(completed) < 2:
        return []
    step = _bar_step(completed)
    current_key = fx_week_key(signal_time)
    groups: dict[str, list[Candle]] = defaultdict(list)
    for candle in completed:
        groups[fx_bar_week_key(candle.time, step)].append(candle)
    prior_keys = sorted(key for key in groups if key < current_key)
    if not prior_keys:
        return []
    prior = groups[prior_keys[-1]]
    return [
        LiquidityLevel(LiquidityKind.PRIOR_WEEK_HIGH, max(c.high for c in prior), Decimal("1.0"), prior[-1].time),
        LiquidityLevel(LiquidityKind.PRIOR_WEEK_LOW, min(c.low for c in prior), Decimal("1.0"), prior[-1].time),
    ]


def _completed_session_levels(
    candles: list[Candle],
    *,
    signal_time: datetime,
    definition: SessionDefinition,
    high_kind: LiquidityKind,
    low_kind: LiquidityKind,
    strength: Decimal,
) -> list[LiquidityLevel]:
    groups: dict[object, list[Candle]] = defaultdict(list)
    for candle in candles:
        local = candle.time.astimezone(definition.zone)
        current = local.timetz().replace(tzinfo=None)
        if definition.local_open <= current < definition.local_close:
            groups[local.date()].append(candle)
    eligible: list[tuple[datetime, list[Candle]]] = []
    for session_date, members in groups.items():
        end_local = datetime.combine(session_date, definition.local_close, tzinfo=definition.zone)
        if end_local <= signal_time.astimezone(definition.zone):
            eligible.append((end_local, members))
    if not eligible:
        return []
    _, members = max(eligible, key=lambda item: item[0])
    return [
        LiquidityLevel(high_kind, max(c.high for c in members), strength, members[-1].time),
        LiquidityLevel(low_kind, min(c.low for c in members), strength, members[-1].time),
    ]


def _opening_range_levels(
    candles: list[Candle],
    *,
    signal_time: datetime,
    definition: SessionDefinition,
    high_kind: LiquidityKind,
    low_kind: LiquidityKind,
    strength: Decimal,
    range_minutes: int = 30,
) -> list[LiquidityLevel]:
    groups: dict[object, list[Candle]] = defaultdict(list)
    for candle in candles:
        local = candle.time.astimezone(definition.zone)
        open_local = datetime.combine(local.date(), definition.local_open, tzinfo=definition.zone)
        range_end = open_local + timedelta(minutes=range_minutes)
        if open_local <= local < range_end:
            groups[local.date()].append(candle)
    eligible: list[tuple[datetime, list[Candle]]] = []
    signal_local = signal_time.astimezone(definition.zone)
    for session_date, members in groups.items():
        open_local = datetime.combine(session_date, definition.local_open, tzinfo=definition.zone)
        range_end = open_local + timedelta(minutes=range_minutes)
        if range_end <= signal_local:
            eligible.append((range_end, members))
    if not eligible:
        return []
    _, members = max(eligible, key=lambda item: item[0])
    return [
        LiquidityLevel(high_kind, max(c.high for c in members), strength, members[-1].time),
        LiquidityLevel(low_kind, min(c.low for c in members), strength, members[-1].time),
    ]


def _recent_external_swings(points: list[object], kind: LiquidityKind, *, count: int = 5) -> list[LiquidityLevel]:
    results: list[LiquidityLevel] = []
    selected = points[-count:]
    for age, point in enumerate(reversed(selected)):
        strength = max(Decimal("0.50"), Decimal("0.75") - Decimal(age) * Decimal("0.05"))
        results.append(
            LiquidityLevel(
                kind,
                Decimal(str(getattr(point, "price"))),
                strength,
                getattr(point, "time", None),
            )
        )
    return results


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
    return candidate if (candidate.candle_index, candidate.level.strength) > (current.candle_index, current.level.strength) else current
