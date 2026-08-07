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


@dataclass(frozen=True, slots=True)
class EntryStyleReport:
    style: OrderStyle
    scenarios: int
    fills: int
    fill_rate: Decimal
    average_bars_to_fill: Decimal
    average_opportunity_cost_r: Decimal
    average_adverse_selection_r: Decimal


def evaluate_entry_style(
    candidate: TradeCandidate,
    future_candles: Iterable[Candle],
    style: OrderStyle,
    *,
    offset_r: Decimal = Decimal("0.25"),
    slippage_pips: Decimal = Decimal("0"),
    maximum_bars: int = 6,
) -> EntryStyleOutcome:
    if candidate.disposition is not DecisionDisposition.TRADE:
        raise ValueError("candidate must be tradeable")
    if candidate.entry_price is None or candidate.stop_loss is None or candidate.take_profit is None:
        raise ValueError("candidate requires entry, stop and target")
    if candidate.direction not in {Direction.LONG, Direction.SHORT}:
        raise ValueError("flat candidates cannot be evaluated")
    if offset_r < 0 or slippage_pips < 0 or maximum_bars < 1:
        raise ValueError("entry-style parameters are invalid")
    candles = [item for item in future_candles if item.complete][:maximum_bars]
    if not candles:
        raise ValueError("at least one completed future candle is required")
    entry = candidate.entry_price
    risk = abs(entry - candidate.stop_loss)
    if risk <= 0:
        raise ValueError("candidate risk must be positive")
    slip = pip_size(candidate.instrument) * slippage_pips

    if style is OrderStyle.MARKET:
        fill = entry + slip if candidate.direction is Direction.LONG else entry - slip
        return EntryStyleOutcome(style, True, fill, 0, Decimal("0"), _post_fill_adverse(candidate.direction, fill, candles[0], risk))

    if style is OrderStyle.LIMIT:
        trigger = entry - risk * offset_r if candidate.direction is Direction.LONG else entry + risk * offset_r
    elif style is OrderStyle.MARKET_IF_TOUCHED:
        trigger = entry - risk * offset_r if candidate.direction is Direction.LONG else entry + risk * offset_r
    elif style is OrderStyle.STOP:
        trigger = entry + risk * offset_r if candidate.direction is Direction.LONG else entry - risk * offset_r
    else:
        raise ValueError(f"unsupported order style: {style}")

    best_favorable_r = Decimal("0")
    for index, candle in enumerate(candles, start=1):
        favorable = (
            (candle.high - entry) / risk
            if candidate.direction is Direction.LONG
            else (entry - candle.low) / risk
        )
        best_favorable_r = max(best_favorable_r, favorable)
        touched = candle.low <= trigger <= candle.high
        if not touched:
            continue
        if style is OrderStyle.LIMIT:
            fill = trigger
        else:
            fill = trigger + slip if candidate.direction is Direction.LONG else trigger - slip
        adverse = _post_fill_adverse(candidate.direction, fill, candle, risk)
        opportunity = max(Decimal("0"), best_favorable_r - max(Decimal("0"), _directional_r(candidate.direction, entry, fill, risk)))
        return EntryStyleOutcome(style, True, fill, index, opportunity, adverse)
    return EntryStyleOutcome(style, False, None, None, max(Decimal("0"), best_favorable_r), Decimal("0"))


def compare_entry_styles(
    scenarios: Iterable[tuple[TradeCandidate, Iterable[Candle]]],
    styles: Iterable[OrderStyle] = tuple(OrderStyle),
    *,
    offset_r: Decimal = Decimal("0.25"),
    slippage_pips: Decimal = Decimal("0"),
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
            )
        )
    return tuple(reports)


def _directional_r(direction: Direction, origin: Decimal, price: Decimal, risk: Decimal) -> Decimal:
    return (price - origin) / risk if direction is Direction.LONG else (origin - price) / risk


def _post_fill_adverse(direction: Direction, fill: Decimal, candle: Candle, risk: Decimal) -> Decimal:
    if direction is Direction.LONG:
        return max(Decimal("0"), (fill - candle.low) / risk)
    return max(Decimal("0"), (candle.high - fill) / risk)
