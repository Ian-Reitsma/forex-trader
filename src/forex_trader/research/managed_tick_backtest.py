from __future__ import annotations

import bisect
import math
from dataclasses import dataclass, replace
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Sequence

from forex_trader.domain.enums import DecisionDisposition, Direction
from forex_trader.domain.macro_history import MacroObservation, PointInTimeFundamentalBook
from forex_trader.domain.models import Quote, TradeCandidate
from forex_trader.domain.sessions import classify_phase
from forex_trader.domain.strategy import SignalFusionPolicy
from forex_trader.domain.technicals import assess_technicals, pip_size
from forex_trader.research.backtest import BacktestTrade, OutcomeStatus
from forex_trader.research.public_history import HistoricalTick, resample_midpoint_candles
from forex_trader.research.tick_backtest import (
    ExactTickOutcome,
    SelectionScore,
    StrategyFilter,
    TickBacktestOpportunity,
    evaluate_frozen_filter,
    select_filters_on_calibration,
)


DEFAULT_PROFIT_TARGETS_R: tuple[Decimal, ...] = (
    Decimal("0.35"),
    Decimal("0.50"),
    Decimal("0.65"),
    Decimal("0.80"),
    Decimal("1.00"),
)


@dataclass(frozen=True, slots=True)
class ManagedSelectionScore:
    take_profit_r: Decimal
    selection: SelectionScore


@dataclass(frozen=True, slots=True)
class ManagedWalkForwardSelection:
    take_profit_r: Decimal
    frozen: object


def _validate_targets(targets: Sequence[Decimal]) -> tuple[Decimal, ...]:
    normalized = tuple(sorted(set(targets)))
    if not normalized:
        raise ValueError("at least one take-profit target is required")
    if any(target <= 0 or target > Decimal("1") for target in normalized):
        raise ValueError("managed take-profit targets must be in (0,1]")
    return normalized


def evaluate_candidate_on_ticks_for_targets(
    candidate: TradeCandidate,
    ticks: Sequence[HistoricalTick],
    *,
    entry_index: int,
    take_profit_targets_r: Sequence[Decimal] = DEFAULT_PROFIT_TARGETS_R,
    maximum_holding: timedelta = timedelta(hours=2),
    adverse_slippage_pips: Decimal = Decimal("0.10"),
) -> dict[Decimal, ExactTickOutcome]:
    """Evaluate several fixed-R profit targets in one exact bid/ask tick pass.

    Every profile keeps the candidate's original structural stop. A target is only
    counted as a win if the executable exit side reaches that target before the stop.
    The same observed spread, entry latency (handled by the caller), and adverse
    slippage model used by the base exact-tick backtest are preserved.
    """
    targets = _validate_targets(take_profit_targets_r)
    if candidate.disposition is not DecisionDisposition.TRADE:
        raise ValueError("candidate must be tradeable")
    if candidate.entry_price is None or candidate.stop_loss is None or candidate.take_profit is None:
        raise ValueError("candidate must have entry, stop, and target")
    if not 0 <= entry_index < len(ticks):
        raise ValueError("entry_index is outside tick history")
    if maximum_holding <= timedelta(0):
        raise ValueError("maximum_holding must be positive")
    if adverse_slippage_pips < 0:
        raise ValueError("adverse_slippage_pips cannot be negative")

    entry_tick = ticks[entry_index]
    if entry_tick.instrument.upper() != candidate.instrument.upper():
        raise ValueError("candidate and tick instruments do not match")
    pip = pip_size(candidate.instrument)
    slippage = pip * adverse_slippage_pips
    if candidate.direction is Direction.LONG:
        entry_fill = entry_tick.ask + slippage
        if entry_fill <= candidate.stop_loss:
            raise ValueError("long managed entry must remain above structural stop")
    elif candidate.direction is Direction.SHORT:
        entry_fill = entry_tick.bid - slippage
        if entry_fill >= candidate.stop_loss:
            raise ValueError("short managed entry must remain below structural stop")
    else:
        raise ValueError("flat candidate cannot be backtested")

    risk = abs(entry_fill - candidate.stop_loss)
    if risk <= 0:
        raise ValueError("candidate stop distance must be positive")
    target_prices = {
        target: (
            entry_fill + risk * target
            if candidate.direction is Direction.LONG
            else entry_fill - risk * target
        )
        for target in targets
    }
    deadline = entry_tick.time + maximum_holding
    unresolved = set(targets)
    max_favorable = {target: Decimal("0") for target in targets}
    max_adverse = {target: Decimal("0") for target in targets}
    outcomes: dict[Decimal, ExactTickOutcome] = {}
    last_tick = entry_tick
    one_way_cost_r = slippage / risk

    for tick_index in range(entry_index, len(ticks)):
        tick = ticks[tick_index]
        if tick.time > deadline:
            break
        last_tick = tick
        if candidate.direction is Direction.LONG:
            exit_side = tick.bid
            favorable = max(Decimal("0"), (exit_side - entry_fill) / risk)
            adverse = max(Decimal("0"), (entry_fill - exit_side) / risk)
            stop_hit = exit_side <= candidate.stop_loss
        else:
            exit_side = tick.ask
            favorable = max(Decimal("0"), (entry_fill - exit_side) / risk)
            adverse = max(Decimal("0"), (exit_side - entry_fill) / risk)
            stop_hit = exit_side >= candidate.stop_loss

        for target in unresolved:
            max_favorable[target] = max(max_favorable[target], favorable)
            max_adverse[target] = max(max_adverse[target], adverse)

        if stop_hit:
            if candidate.direction is Direction.LONG:
                fill = min(exit_side, candidate.stop_loss) - slippage
                realized = (fill - entry_fill) / risk
            else:
                fill = max(exit_side, candidate.stop_loss) + slippage
                realized = (entry_fill - fill) / risk
            bars_held = max(1, math.ceil((tick.time - entry_tick.time).total_seconds() / 300))
            for target in tuple(unresolved):
                trade = BacktestTrade(
                    candidate.instrument,
                    candidate.direction,
                    candidate.signal_time,
                    candidate.score,
                    OutcomeStatus.LOSS,
                    realized,
                    bars_held,
                    exit_reason=f"managed_tick_stop@{target}R",
                    entry_fill=entry_fill,
                    exit_fill=fill,
                    maximum_favorable_r=max_favorable[target],
                    maximum_adverse_r=max_adverse[target],
                    estimated_cost_r=one_way_cost_r * Decimal("2"),
                )
                outcomes[target] = ExactTickOutcome(trade, entry_tick.time, tick.time)
                unresolved.remove(target)
            break

        for target in tuple(unresolved):
            target_price = target_prices[target]
            target_hit = (
                exit_side >= target_price
                if candidate.direction is Direction.LONG
                else exit_side <= target_price
            )
            if not target_hit:
                continue
            if candidate.direction is Direction.LONG:
                fill = target_price - slippage
                realized = (fill - entry_fill) / risk
            else:
                fill = target_price + slippage
                realized = (entry_fill - fill) / risk
            bars_held = max(1, math.ceil((tick.time - entry_tick.time).total_seconds() / 300))
            trade = BacktestTrade(
                candidate.instrument,
                candidate.direction,
                candidate.signal_time,
                candidate.score,
                OutcomeStatus.WIN,
                realized,
                bars_held,
                exit_reason=f"managed_tick_target@{target}R",
                entry_fill=entry_fill,
                exit_fill=fill,
                maximum_favorable_r=max_favorable[target],
                maximum_adverse_r=max_adverse[target],
                estimated_cost_r=one_way_cost_r * Decimal("2"),
            )
            outcomes[target] = ExactTickOutcome(trade, entry_tick.time, tick.time)
            unresolved.remove(target)
        if not unresolved:
            break

    for target in tuple(unresolved):
        if candidate.direction is Direction.LONG:
            exit_fill = last_tick.bid - slippage
            realized = (exit_fill - entry_fill) / risk
        else:
            exit_fill = last_tick.ask + slippage
            realized = (entry_fill - exit_fill) / risk
        trade = BacktestTrade(
            candidate.instrument,
            candidate.direction,
            candidate.signal_time,
            candidate.score,
            OutcomeStatus.TIMEOUT,
            realized,
            max(1, math.ceil((last_tick.time - entry_tick.time).total_seconds() / 300)),
            exit_reason=f"managed_tick_time_stop@{target}R",
            entry_fill=entry_fill,
            exit_fill=exit_fill,
            maximum_favorable_r=max_favorable[target],
            maximum_adverse_r=max_adverse[target],
            estimated_cost_r=one_way_cost_r * Decimal("2"),
        )
        outcomes[target] = ExactTickOutcome(trade, entry_tick.time, last_tick.time)
    return outcomes


def _latest_news_age_minutes(
    observations: Sequence[MacroObservation],
    *,
    currencies: tuple[str, str],
    as_of: datetime,
) -> Decimal | None:
    latest: datetime | None = None
    allowed = set(currencies)
    for observation in observations:
        if observation.available_at > as_of:
            break
        if observation.currency in allowed:
            latest = observation.available_at
    if latest is None:
        return None
    return Decimal(str((as_of - latest).total_seconds() / 60))


def generate_profit_target_opportunities(
    *,
    instrument: str,
    ticks: Sequence[HistoricalTick],
    fundamentals: PointInTimeFundamentalBook,
    news_observations: Sequence[MacroObservation] = (),
    take_profit_targets_r: Sequence[Decimal] = DEFAULT_PROFIT_TARGETS_R,
    lower_timeframe: timedelta = timedelta(minutes=5),
    higher_timeframe: timedelta = timedelta(hours=1),
    maximum_holding: timedelta = timedelta(hours=2),
    entry_latency: timedelta = timedelta(milliseconds=500),
    adverse_slippage_pips: Decimal = Decimal("0.10"),
    maximum_decision_quote_age: timedelta = timedelta(seconds=10),
) -> dict[Decimal, tuple[TickBacktestOpportunity, ...]]:
    """Generate identical entries with several exact fixed-R take-profit profiles."""
    targets = _validate_targets(take_profit_targets_r)
    if len(ticks) < 2:
        return {target: () for target in targets}
    ordered_ticks = tuple(sorted(ticks, key=lambda item: item.time))
    times = [item.time for item in ordered_ticks]
    lower = list(resample_midpoint_candles(ordered_ticks, timeframe=lower_timeframe))
    higher = list(resample_midpoint_candles(ordered_ticks, timeframe=higher_timeframe))
    if len(lower) < 82 or len(higher) < 60:
        return {target: () for target in targets}
    higher_ready = [candle.time + higher_timeframe for candle in higher]

    normalized = instrument.upper()
    base_currency, quote_currency = normalized.split("_", maxsplit=1)
    policy = SignalFusionPolicy(
        minimum_score=Decimal("0"),
        minimum_fundamental_confidence=Decimal("0"),
        maximum_spread_pips=Decimal("5"),
        maximum_quote_signal_gap_seconds=max(30, int(maximum_decision_quote_age.total_seconds()) + 5),
        minimum_reward_risk=Decimal("1.01"),
        require_fundamentals=False,
        require_liquidity_sweep=True,
        require_displacement=False,
        require_structure_shift=True,
        require_entry_confirmed=True,
        minimum_location_score=Decimal("0.15"),
    )

    opportunities: dict[Decimal, list[TickBacktestOpportunity]] = {target: [] for target in targets}
    for index in range(79, len(lower) - 1):
        signal_candle = lower[index]
        decision_time = signal_candle.time + lower_timeframe
        higher_count = bisect.bisect_right(higher_ready, decision_time)
        if higher_count < 60:
            continue

        decision_tick_index = bisect.bisect_left(times, decision_time)
        if decision_tick_index >= len(ordered_ticks):
            continue
        decision_tick = ordered_ticks[decision_tick_index]
        if decision_tick.time - decision_time > maximum_decision_quote_age:
            continue

        technical = assess_technicals(
            normalized,
            lower[max(0, index - 199) : index + 1],
            higher[max(0, higher_count - 200) : higher_count],
            minimum_structural_reward_risk=Decimal("1.01"),
        )
        fundamental = fundamentals.assess_pair(normalized, as_of=decision_time)
        decision_quote = Quote(normalized, decision_tick.bid, decision_tick.ask, decision_tick.time)
        candidate = policy.evaluate(technical, fundamental, decision_quote)
        if candidate.disposition is not DecisionDisposition.TRADE:
            continue

        send_index = bisect.bisect_left(times, decision_time + entry_latency)
        if send_index >= len(ordered_ticks):
            continue
        send_tick = ordered_ticks[send_index]
        if send_tick.time - decision_time > maximum_decision_quote_age:
            continue
        send_quote = Quote(normalized, send_tick.bid, send_tick.ask, send_tick.time)
        candidate = policy.revalidate_execution(candidate, send_quote, maximum_spread_pips=Decimal("5"))
        if candidate.disposition is not DecisionDisposition.TRADE:
            continue
        assert candidate.entry_price is not None
        assert candidate.stop_loss is not None
        assert candidate.take_profit is not None
        executable_rr = abs(candidate.take_profit - candidate.entry_price) / abs(candidate.entry_price - candidate.stop_loss)
        outcomes = evaluate_candidate_on_ticks_for_targets(
            candidate,
            ordered_ticks,
            entry_index=send_index,
            take_profit_targets_r=targets,
            maximum_holding=maximum_holding,
            adverse_slippage_pips=adverse_slippage_pips,
        )
        directional_news = fundamental.differential if candidate.direction is Direction.LONG else -fundamental.differential
        for target, outcome in outcomes.items():
            opportunities[target].append(
                TickBacktestOpportunity(
                    instrument=normalized,
                    decision_time=decision_time,
                    entry_time=outcome.entry_time,
                    exit_time=outcome.exit_time,
                    trade=replace(outcome.trade, score=technical.score),
                    technical_score=technical.score,
                    reward_risk=executable_rr,
                    spread_pips=send_tick.spread / pip_size(normalized),
                    displacement=technical.displacement,
                    session_phase=classify_phase(decision_time),
                    news_directional=directional_news,
                    news_confidence=fundamental.confidence,
                    latest_news_age_minutes=_latest_news_age_minutes(
                        news_observations,
                        currencies=(base_currency, quote_currency),
                        as_of=decision_time,
                    ),
                    setup_family=technical.setup_family,
                )
            )
    return {target: tuple(items) for target, items in opportunities.items()}


def select_managed_profiles_on_calibration(
    opportunities_by_target: dict[Decimal, Sequence[TickBacktestOpportunity]],
    *,
    calibration_start: datetime,
    calibration_end: datetime,
    filter_grid: Sequence[StrategyFilter] | None = None,
    minimum_trades: int = 20,
) -> tuple[ManagedSelectionScore, ManagedSelectionScore]:
    """Select profit target and entry filter strictly from the calibration interval."""
    robust_candidates: list[ManagedSelectionScore] = []
    win_candidates: list[ManagedSelectionScore] = []
    for target, opportunities in sorted(opportunities_by_target.items()):
        try:
            robust, win_target = select_filters_on_calibration(
                opportunities,
                calibration_start=calibration_start,
                calibration_end=calibration_end,
                filter_grid=filter_grid,
                minimum_trades=minimum_trades,
            )
        except ValueError:
            continue
        robust_candidates.append(ManagedSelectionScore(target, robust))
        win_candidates.append(ManagedSelectionScore(target, win_target))
    if not robust_candidates or not win_candidates:
        raise ValueError("no managed target/filter combination produced enough positive-expectancy calibration trades")

    robust_best = max(
        robust_candidates,
        key=lambda item: (
            item.selection.lower_confidence_expectancy_r,
            item.selection.report.expectancy_r,
            item.selection.report.win_rate,
            -item.selection.report.max_drawdown_r,
            item.selection.report.trades,
            item.take_profit_r,
        ),
    )
    positive_lower = [item for item in win_candidates if item.selection.lower_confidence_expectancy_r > 0]
    win_pool = positive_lower or win_candidates
    win_best = max(
        win_pool,
        key=lambda item: (
            min(item.selection.report.win_rate, Decimal("0.75")),
            item.selection.lower_confidence_expectancy_r,
            item.selection.report.expectancy_r,
            -item.selection.report.max_drawdown_r,
            item.selection.report.trades,
            item.take_profit_r,
        ),
    )
    return robust_best, win_best


def evaluate_managed_selection(
    opportunities_by_target: dict[Decimal, Sequence[TickBacktestOpportunity]],
    *,
    managed_selection: ManagedSelectionScore,
    calibration_start: datetime,
    calibration_end: datetime,
    holdout_end: datetime,
    objective: str,
    risk_fraction_per_trade: Decimal = Decimal("0.0015"),
) -> ManagedWalkForwardSelection:
    opportunities = opportunities_by_target[managed_selection.take_profit_r]
    frozen = evaluate_frozen_filter(
        opportunities,
        selection=managed_selection.selection,
        calibration_start=calibration_start,
        calibration_end=calibration_end,
        holdout_end=holdout_end,
        objective=objective,
        risk_fraction_per_trade=risk_fraction_per_trade,
    )
    return ManagedWalkForwardSelection(managed_selection.take_profit_r, frozen)
