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
    StrategyFilter,
    TickBacktestOpportunity,
    select_filters_on_calibration,
)


@dataclass(frozen=True, slots=True, order=True)
class PartialRunnerProfile:
    first_target_r: Decimal
    first_exit_fraction: Decimal
    runner_target_r: Decimal

    def __post_init__(self) -> None:
        if not Decimal("0") < self.first_target_r < self.runner_target_r:
            raise ValueError("expected 0 < first_target_r < runner_target_r")
        if not Decimal("0") < self.first_exit_fraction < Decimal("1"):
            raise ValueError("first_exit_fraction must be in (0,1)")

    @property
    def identity(self) -> str:
        return (
            f"first={self.first_target_r}R|fraction={self.first_exit_fraction}|"
            f"runner={self.runner_target_r}R|stop=breakeven_after_first"
        )


DEFAULT_PARTIAL_RUNNER_PROFILES: tuple[PartialRunnerProfile, ...] = tuple(
    PartialRunnerProfile(first, fraction, runner)
    for first in (Decimal("0.25"), Decimal("0.33"), Decimal("0.35"), Decimal("0.40"))
    for fraction in (Decimal("0.50"), Decimal("0.67"), Decimal("0.75"))
    for runner in (Decimal("1.00"), Decimal("1.50"), Decimal("2.00"))
)


@dataclass(slots=True)
class _ProfileState:
    first_hit: bool = False
    first_realized_r: Decimal = Decimal("0")
    max_favorable_r: Decimal = Decimal("0")
    max_adverse_r: Decimal = Decimal("0")


def _economic_status(realized_r: Decimal) -> OutcomeStatus:
    if realized_r > 0:
        return OutcomeStatus.WIN
    if realized_r < 0:
        return OutcomeStatus.LOSS
    return OutcomeStatus.TIMEOUT


def evaluate_candidate_on_ticks_for_partial_runners(
    candidate: TradeCandidate,
    ticks: Sequence[HistoricalTick],
    *,
    entry_index: int,
    profiles: Sequence[PartialRunnerProfile] = DEFAULT_PARTIAL_RUNNER_PROFILES,
    maximum_holding: timedelta = timedelta(hours=2),
    adverse_slippage_pips: Decimal = Decimal("0.10"),
) -> dict[PartialRunnerProfile, BacktestTrade]:
    """Evaluate partial-profit + break-even runner profiles in one exact tick pass.

    The original structural stop remains in force until the first target executes. After
    the partial exit, only the remaining fraction is protected at break-even and can run
    to the larger target. All triggers use the executable exit side and all fills retain
    the same adverse-slippage model as the base exact-tick backtest.
    """
    profile_tuple = tuple(sorted(set(profiles)))
    if not profile_tuple:
        raise ValueError("at least one partial-runner profile is required")
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
            raise ValueError("long entry must remain above structural stop")
    elif candidate.direction is Direction.SHORT:
        entry_fill = entry_tick.bid - slippage
        if entry_fill >= candidate.stop_loss:
            raise ValueError("short entry must remain below structural stop")
    else:
        raise ValueError("flat candidate cannot be backtested")

    risk = abs(entry_fill - candidate.stop_loss)
    if risk <= 0:
        raise ValueError("candidate stop distance must be positive")
    first_prices = {
        profile: (
            entry_fill + risk * profile.first_target_r
            if candidate.direction is Direction.LONG
            else entry_fill - risk * profile.first_target_r
        )
        for profile in profile_tuple
    }
    runner_prices = {
        profile: (
            entry_fill + risk * profile.runner_target_r
            if candidate.direction is Direction.LONG
            else entry_fill - risk * profile.runner_target_r
        )
        for profile in profile_tuple
    }
    states = {profile: _ProfileState() for profile in profile_tuple}
    unresolved = set(profile_tuple)
    outcomes: dict[PartialRunnerProfile, BacktestTrade] = {}
    deadline = entry_tick.time + maximum_holding
    last_tick = entry_tick
    entry_cost_r = slippage / risk

    for tick_index in range(entry_index, len(ticks)):
        tick = ticks[tick_index]
        if tick.time > deadline:
            break
        last_tick = tick
        if candidate.direction is Direction.LONG:
            exit_side = tick.bid
            favorable = max(Decimal("0"), (exit_side - entry_fill) / risk)
            adverse = max(Decimal("0"), (entry_fill - exit_side) / risk)
            structural_stop_hit = exit_side <= candidate.stop_loss
        else:
            exit_side = tick.ask
            favorable = max(Decimal("0"), (entry_fill - exit_side) / risk)
            adverse = max(Decimal("0"), (exit_side - entry_fill) / risk)
            structural_stop_hit = exit_side >= candidate.stop_loss

        for profile in tuple(unresolved):
            state = states[profile]
            state.max_favorable_r = max(state.max_favorable_r, favorable)
            state.max_adverse_r = max(state.max_adverse_r, adverse)
            remaining = Decimal("1") - profile.first_exit_fraction

            if not state.first_hit:
                if structural_stop_hit:
                    if candidate.direction is Direction.LONG:
                        fill = min(exit_side, candidate.stop_loss) - slippage
                        realized = (fill - entry_fill) / risk
                    else:
                        fill = max(exit_side, candidate.stop_loss) + slippage
                        realized = (entry_fill - fill) / risk
                    outcomes[profile] = BacktestTrade(
                        candidate.instrument,
                        candidate.direction,
                        candidate.signal_time,
                        candidate.score,
                        OutcomeStatus.LOSS,
                        realized,
                        max(1, math.ceil((tick.time - entry_tick.time).total_seconds() / 300)),
                        exit_reason=f"partial_runner_structural_stop|{profile.identity}",
                        entry_fill=entry_fill,
                        exit_fill=fill,
                        maximum_favorable_r=state.max_favorable_r,
                        maximum_adverse_r=state.max_adverse_r,
                        estimated_cost_r=entry_cost_r + slippage / risk,
                    )
                    unresolved.remove(profile)
                    continue

                first_price = first_prices[profile]
                first_hit = (
                    exit_side >= first_price
                    if candidate.direction is Direction.LONG
                    else exit_side <= first_price
                )
                if not first_hit:
                    continue
                if candidate.direction is Direction.LONG:
                    first_fill = first_price - slippage
                    first_leg_r = (first_fill - entry_fill) / risk
                else:
                    first_fill = first_price + slippage
                    first_leg_r = (entry_fill - first_fill) / risk
                state.first_hit = True
                state.first_realized_r = first_leg_r * profile.first_exit_fraction

            runner_price = runner_prices[profile]
            if candidate.direction is Direction.LONG:
                runner_hit = exit_side >= runner_price
                breakeven_hit = exit_side <= entry_fill
            else:
                runner_hit = exit_side <= runner_price
                breakeven_hit = exit_side >= entry_fill

            if runner_hit:
                if candidate.direction is Direction.LONG:
                    runner_fill = runner_price - slippage
                    runner_r = (runner_fill - entry_fill) / risk
                else:
                    runner_fill = runner_price + slippage
                    runner_r = (entry_fill - runner_fill) / risk
                realized = state.first_realized_r + runner_r * remaining
                outcomes[profile] = BacktestTrade(
                    candidate.instrument,
                    candidate.direction,
                    candidate.signal_time,
                    candidate.score,
                    _economic_status(realized),
                    realized,
                    max(1, math.ceil((tick.time - entry_tick.time).total_seconds() / 300)),
                    exit_reason=f"partial_runner_target|{profile.identity}",
                    entry_fill=entry_fill,
                    exit_fill=runner_fill,
                    maximum_favorable_r=state.max_favorable_r,
                    maximum_adverse_r=state.max_adverse_r,
                    estimated_cost_r=(
                        entry_cost_r
                        + (slippage / risk) * profile.first_exit_fraction
                        + (slippage / risk) * remaining
                    ),
                )
                unresolved.remove(profile)
                continue

            if breakeven_hit:
                if candidate.direction is Direction.LONG:
                    runner_fill = min(exit_side, entry_fill) - slippage
                    runner_r = (runner_fill - entry_fill) / risk
                else:
                    runner_fill = max(exit_side, entry_fill) + slippage
                    runner_r = (entry_fill - runner_fill) / risk
                realized = state.first_realized_r + runner_r * remaining
                outcomes[profile] = BacktestTrade(
                    candidate.instrument,
                    candidate.direction,
                    candidate.signal_time,
                    candidate.score,
                    _economic_status(realized),
                    realized,
                    max(1, math.ceil((tick.time - entry_tick.time).total_seconds() / 300)),
                    exit_reason=f"partial_runner_breakeven|{profile.identity}",
                    entry_fill=entry_fill,
                    exit_fill=runner_fill,
                    maximum_favorable_r=state.max_favorable_r,
                    maximum_adverse_r=state.max_adverse_r,
                    estimated_cost_r=(
                        entry_cost_r
                        + (slippage / risk) * profile.first_exit_fraction
                        + (slippage / risk) * remaining
                    ),
                )
                unresolved.remove(profile)

        if not unresolved:
            break

    for profile in tuple(unresolved):
        state = states[profile]
        remaining = Decimal("1") - profile.first_exit_fraction
        if candidate.direction is Direction.LONG:
            final_fill = last_tick.bid - slippage
            final_r = (final_fill - entry_fill) / risk
        else:
            final_fill = last_tick.ask + slippage
            final_r = (entry_fill - final_fill) / risk
        realized = (
            state.first_realized_r + final_r * remaining
            if state.first_hit
            else final_r
        )
        outcomes[profile] = BacktestTrade(
            candidate.instrument,
            candidate.direction,
            candidate.signal_time,
            candidate.score,
            _economic_status(realized),
            realized,
            max(1, math.ceil((last_tick.time - entry_tick.time).total_seconds() / 300)),
            exit_reason=f"partial_runner_time_stop|{profile.identity}",
            entry_fill=entry_fill,
            exit_fill=final_fill,
            maximum_favorable_r=state.max_favorable_r,
            maximum_adverse_r=state.max_adverse_r,
            estimated_cost_r=(
                entry_cost_r + slippage / risk
                if not state.first_hit
                else entry_cost_r
                + (slippage / risk) * profile.first_exit_fraction
                + (slippage / risk) * remaining
            ),
        )
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


def generate_partial_runner_opportunities(
    *,
    instrument: str,
    ticks: Sequence[HistoricalTick],
    fundamentals: PointInTimeFundamentalBook,
    news_observations: Sequence[MacroObservation] = (),
    profiles: Sequence[PartialRunnerProfile] = DEFAULT_PARTIAL_RUNNER_PROFILES,
    lower_timeframe: timedelta = timedelta(minutes=5),
    higher_timeframe: timedelta = timedelta(hours=1),
    maximum_holding: timedelta = timedelta(hours=2),
    entry_latency: timedelta = timedelta(milliseconds=500),
    adverse_slippage_pips: Decimal = Decimal("0.10"),
    maximum_decision_quote_age: timedelta = timedelta(seconds=10),
) -> dict[PartialRunnerProfile, tuple[TickBacktestOpportunity, ...]]:
    profile_tuple = tuple(sorted(set(profiles)))
    if not profile_tuple:
        raise ValueError("at least one partial-runner profile is required")
    if len(ticks) < 2:
        return {profile: () for profile in profile_tuple}
    ordered_ticks = tuple(sorted(ticks, key=lambda item: item.time))
    times = [item.time for item in ordered_ticks]
    lower = list(resample_midpoint_candles(ordered_ticks, timeframe=lower_timeframe))
    higher = list(resample_midpoint_candles(ordered_ticks, timeframe=higher_timeframe))
    if len(lower) < 82 or len(higher) < 60:
        return {profile: () for profile in profile_tuple}
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
    opportunities: dict[PartialRunnerProfile, list[TickBacktestOpportunity]] = {
        profile: [] for profile in profile_tuple
    }

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
        candidate = policy.evaluate(
            technical,
            fundamental,
            Quote(normalized, decision_tick.bid, decision_tick.ask, decision_tick.time),
        )
        if candidate.disposition is not DecisionDisposition.TRADE:
            continue

        send_index = bisect.bisect_left(times, decision_time + entry_latency)
        if send_index >= len(ordered_ticks):
            continue
        send_tick = ordered_ticks[send_index]
        if send_tick.time - decision_time > maximum_decision_quote_age:
            continue
        candidate = policy.revalidate_execution(
            candidate,
            Quote(normalized, send_tick.bid, send_tick.ask, send_tick.time),
            maximum_spread_pips=Decimal("5"),
        )
        if candidate.disposition is not DecisionDisposition.TRADE:
            continue
        assert candidate.entry_price is not None
        assert candidate.stop_loss is not None
        assert candidate.take_profit is not None
        structural_rr = abs(candidate.take_profit - candidate.entry_price) / abs(
            candidate.entry_price - candidate.stop_loss
        )
        outcomes = evaluate_candidate_on_ticks_for_partial_runners(
            candidate,
            ordered_ticks,
            entry_index=send_index,
            profiles=profile_tuple,
            maximum_holding=maximum_holding,
            adverse_slippage_pips=adverse_slippage_pips,
        )
        directional_news = (
            fundamental.differential
            if candidate.direction is Direction.LONG
            else -fundamental.differential
        )
        latest_age = _latest_news_age_minutes(
            news_observations,
            currencies=(base_currency, quote_currency),
            as_of=decision_time,
        )
        for profile, trade in outcomes.items():
            opportunities[profile].append(
                TickBacktestOpportunity(
                    instrument=normalized,
                    decision_time=decision_time,
                    entry_time=send_tick.time,
                    exit_time=trade.signal_time + timedelta(minutes=trade.bars_held * 5),
                    trade=replace(trade, score=technical.score),
                    technical_score=technical.score,
                    reward_risk=structural_rr,
                    spread_pips=send_tick.spread / pip_size(normalized),
                    displacement=technical.displacement,
                    session_phase=classify_phase(decision_time),
                    news_directional=directional_news,
                    news_confidence=fundamental.confidence,
                    latest_news_age_minutes=latest_age,
                    setup_family=technical.setup_family,
                )
            )
    return {profile: tuple(values) for profile, values in opportunities.items()}


def select_partial_runner_profiles_on_calibration(
    opportunities_by_profile: dict[PartialRunnerProfile, Sequence[TickBacktestOpportunity]],
    *,
    calibration_start: datetime,
    calibration_end: datetime,
    filter_grid: Sequence[StrategyFilter] | None = None,
    minimum_trades: int = 20,
) -> tuple[tuple[PartialRunnerProfile, object], tuple[PartialRunnerProfile, object]]:
    """Select profile + entry filter only from calibration data.

    The first result maximizes lower-confidence expectancy; the second maximizes economic
    win rate up to the 75% goal while retaining positive expectancy whenever possible.
    """
    candidates: list[tuple[PartialRunnerProfile, object, object]] = []
    for profile, opportunities in sorted(opportunities_by_profile.items()):
        try:
            robust, win = select_filters_on_calibration(
                opportunities,
                calibration_start=calibration_start,
                calibration_end=calibration_end,
                filter_grid=filter_grid,
                minimum_trades=minimum_trades,
            )
        except ValueError:
            continue
        candidates.append((profile, robust, win))
    if not candidates:
        raise ValueError("no partial-runner profile produced enough positive-expectancy calibration trades")

    robust_profile, robust_score, _ = max(
        candidates,
        key=lambda item: (
            item[1].lower_confidence_expectancy_r,
            item[1].report.expectancy_r,
            item[1].report.win_rate,
        ),
    )
    positive_win = [item for item in candidates if item[2].lower_confidence_expectancy_r > 0]
    win_pool = positive_win or candidates
    win_profile, _, win_score = max(
        win_pool,
        key=lambda item: (
            min(item[2].report.win_rate, Decimal("0.75")),
            item[2].lower_confidence_expectancy_r,
            item[2].report.expectancy_r,
        ),
    )
    return (robust_profile, robust_score), (win_profile, win_score)
