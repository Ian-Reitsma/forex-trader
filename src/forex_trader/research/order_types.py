from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from enum import StrEnum
from typing import Iterable

from forex_trader.domain.enums import DecisionDisposition, Direction
from forex_trader.domain.models import Candle, TradeCandidate
from forex_trader.domain.technicals import pip_size


class OrderStyle(StrEnum):
    MARKET = "market"
    LIMIT = "limit"
    MARKET_IF_TOUCHED = "market_if_touched"
    STOP = "stop"


@dataclass(frozen=True, slots=True)
class EntryStyleOutcome:
    style: OrderStyle
    filled: bool
    fill_price: Decimal | None
    bars_to_fill: int | None
    opportunity_cost_r: Decimal
    adverse_selection_r: Decimal
    termination_reason: str = ""
    ambiguous_pre_fill_bar: bool = False


@dataclass(frozen=True, slots=True)
class EntryStyleReport:
    style: OrderStyle
    scenarios: int
    fills: int
    fill_rate: Decimal
    average_bars_to_fill: Decimal
    average_opportunity_cost_r: Decimal
    average_adverse_selection_r: Decimal
    invalidated_before_fill: int = 0
    target_missed_before_fill: int = 0
    ambiguous_pre_fill: int = 0
    expired_unfilled: int = 0


def evaluate_entry_style(
    candidate: TradeCandidate,
    future_candles: Iterable[Candle],
    style: OrderStyle,
    *,
    offset_r: Decimal = Decimal("0.25"),
    slippage_pips: Decimal = Decimal("0"),
    spread_pips: Decimal = Decimal("0"),
    maximum_bars: int = 6,
) -> EntryStyleOutcome:
    """Replay an entry style without allowing a pending order to survive invalidation.

    Candle paths are intrinsically ambiguous. For pullback entries (limit/MIT), if the
    trigger and either original stop or target are all reachable in the same OHLC bar,
    the pending order is conservatively treated as unresolved/missed rather than granting
    a favorable ordering. A pending order is cancelled when the setup invalidates or its
    structural target is reached before fill.
    """
    if candidate.disposition is not DecisionDisposition.TRADE:
        raise ValueError("candidate must be tradeable")
    if candidate.entry_price is None or candidate.stop_loss is None or candidate.take_profit is None:
        raise ValueError("candidate requires entry, stop and target")
    if candidate.direction not in {Direction.LONG, Direction.SHORT}:
        raise ValueError("flat candidates cannot be evaluated")
    if offset_r < 0 or slippage_pips < 0 or spread_pips < 0 or maximum_bars < 1:
        raise ValueError("entry-style parameters are invalid")
    candles = [item for item in future_candles if item.complete][:maximum_bars]
    if not candles:
        raise ValueError("at least one completed future candle is required")
    entry = candidate.entry_price
    stop = candidate.stop_loss
    target = candidate.take_profit
    risk = abs(entry - stop)
    if risk <= 0:
        raise ValueError("candidate risk must be positive")
    pip = pip_size(candidate.instrument)
    slip = pip * slippage_pips
    half_spread = pip * spread_pips / Decimal("2")

    if style is OrderStyle.MARKET:
        fill = entry + slip if candidate.direction is Direction.LONG else entry - slip
        return EntryStyleOutcome(
            style,
            True,
            fill,
            0,
            Decimal("0"),
            _post_fill_adverse(candidate.direction, fill, candles[0], risk, half_spread),
            "market_immediate",
        )

    if style in {OrderStyle.LIMIT, OrderStyle.MARKET_IF_TOUCHED}:
        trigger = entry - risk * offset_r if candidate.direction is Direction.LONG else entry + risk * offset_r
        trigger_geometry_valid = stop < trigger < entry if candidate.direction is Direction.LONG else entry < trigger < stop
    elif style is OrderStyle.STOP:
        trigger = entry + risk * offset_r if candidate.direction is Direction.LONG else entry - risk * offset_r
        trigger_geometry_valid = entry < trigger < target if candidate.direction is Direction.LONG else target < trigger < entry
    else:
        raise ValueError(f"unsupported order style: {style}")

    best_favorable_r = Decimal("0")
    if not trigger_geometry_valid:
        best_favorable_r = _best_favorable_r(candidate.direction, entry, risk, candles, half_spread)
        return EntryStyleOutcome(
            style,
            False,
            None,
            None,
            max(Decimal("0"), best_favorable_r),
            Decimal("0"),
            "invalid_trigger_geometry",
        )

    for index, candle in enumerate(candles, start=1):
        executable_low, executable_high = _executable_extremes(candidate.direction, candle, half_spread)
        favorable = (
            (executable_high - entry) / risk
            if candidate.direction is Direction.LONG
            else (entry - executable_low) / risk
        )
        best_favorable_r = max(best_favorable_r, favorable)
        touched = executable_low <= trigger <= executable_high
        stop_touched = (
            executable_low <= stop
            if candidate.direction is Direction.LONG
            else executable_high >= stop
        )
        target_touched = (
            executable_high >= target
            if candidate.direction is Direction.LONG
            else executable_low <= target
        )

        if not touched:
            if stop_touched:
                return EntryStyleOutcome(
                    style,
                    False,
                    None,
                    None,
                    max(Decimal("0"), best_favorable_r),
                    Decimal("0"),
                    "invalidated_before_fill",
                )
            if target_touched:
                return EntryStyleOutcome(
                    style,
                    False,
                    None,
                    None,
                    max(Decimal("0"), best_favorable_r),
                    Decimal("0"),
                    "target_before_fill",
                )
            continue

        ambiguous = stop_touched or (style in {OrderStyle.LIMIT, OrderStyle.MARKET_IF_TOUCHED} and target_touched)
        if ambiguous:
            return EntryStyleOutcome(
                style,
                False,
                None,
                None,
                max(Decimal("0"), best_favorable_r),
                Decimal("0"),
                "ambiguous_pre_fill_bar",
                True,
            )

        if style is OrderStyle.LIMIT:
            fill = trigger
        else:
            fill = trigger + slip if candidate.direction is Direction.LONG else trigger - slip
        adverse = _post_fill_adverse(candidate.direction, fill, candle, risk, half_spread)
        opportunity = max(
            Decimal("0"),
            best_favorable_r - max(Decimal("0"), _directional_r(candidate.direction, entry, fill, risk)),
        )
        return EntryStyleOutcome(style, True, fill, index, opportunity, adverse, "filled")

    return EntryStyleOutcome(
        style,
        False,
        None,
        None,
        max(Decimal("0"), best_favorable_r),
        Decimal("0"),
        "expired_unfilled",
    )


def compare_entry_styles(
    scenarios: Iterable[tuple[TradeCandidate, Iterable[Candle]]],
    styles: Iterable[OrderStyle] = tuple(OrderStyle),
    *,
    offset_r: Decimal = Decimal("0.25"),
    slippage_pips: Decimal = Decimal("0"),
    spread_pips: Decimal = Decimal("0"),
    maximum_bars: int = 6,
) -> tuple[EntryStyleReport, ...]:
    scenario_list = [(candidate, tuple(candles)) for candidate, candles in scenarios]
    if not scenario_list:
        raise ValueError("at least one scenario is required")
    reports: list[EntryStyleReport] = []
    for style in styles:
        outcomes = [
            evaluate_entry_style(
                candidate,
                candles,
                style,
                offset_r=offset_r,
                slippage_pips=slippage_pips,
                spread_pips=spread_pips,
                maximum_bars=maximum_bars,
            )
            for candidate, candles in scenario_list
        ]
        filled = [item for item in outcomes if item.filled]
        count = Decimal(len(outcomes))
        reports.append(
            EntryStyleReport(
                style=style,
                scenarios=len(outcomes),
                fills=len(filled),
                fill_rate=Decimal(len(filled)) / count,
                average_bars_to_fill=(
                    sum((Decimal(item.bars_to_fill or 0) for item in filled), Decimal("0")) / Decimal(len(filled))
                    if filled else Decimal("0")
                ),
                average_opportunity_cost_r=sum((item.opportunity_cost_r for item in outcomes), Decimal("0")) / count,
                average_adverse_selection_r=(
                    sum((item.adverse_selection_r for item in filled), Decimal("0")) / Decimal(len(filled))
                    if filled else Decimal("0")
                ),
                invalidated_before_fill=sum(item.termination_reason == "invalidated_before_fill" for item in outcomes),
                target_missed_before_fill=sum(item.termination_reason == "target_before_fill" for item in outcomes),
                ambiguous_pre_fill=sum(item.ambiguous_pre_fill_bar for item in outcomes),
                expired_unfilled=sum(item.termination_reason == "expired_unfilled" for item in outcomes),
            )
        )
    return tuple(reports)


def _directional_r(direction: Direction, origin: Decimal, price: Decimal, risk: Decimal) -> Decimal:
    return (price - origin) / risk if direction is Direction.LONG else (origin - price) / risk


def _executable_extremes(direction: Direction, candle: Candle, half_spread: Decimal) -> tuple[Decimal, Decimal]:
    if direction is Direction.LONG:
        return candle.low + half_spread, candle.high + half_spread
    return candle.low - half_spread, candle.high - half_spread


def _best_favorable_r(
    direction: Direction,
    entry: Decimal,
    risk: Decimal,
    candles: Iterable[Candle],
    half_spread: Decimal,
) -> Decimal:
    best = Decimal("0")
    for candle in candles:
        executable_low, executable_high = _executable_extremes(direction, candle, half_spread)
        favorable = (executable_high - entry) / risk if direction is Direction.LONG else (entry - executable_low) / risk
        best = max(best, favorable)
    return best


def _post_fill_adverse(
    direction: Direction,
    fill: Decimal,
    candle: Candle,
    risk: Decimal,
    half_spread: Decimal,
) -> Decimal:
    executable_low, executable_high = _executable_extremes(direction, candle, half_spread)
    if direction is Direction.LONG:
        return max(Decimal("0"), (fill - executable_low) / risk)
    return max(Decimal("0"), (executable_high - fill) / risk)
