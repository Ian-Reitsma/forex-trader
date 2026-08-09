from __future__ import annotations

import bisect
import itertools
import math
from dataclasses import dataclass, replace
from datetime import date, datetime, timedelta
from decimal import Decimal
from enum import StrEnum
from typing import Iterable, Sequence
from zoneinfo import ZoneInfo

from forex_trader.domain.enums import DecisionDisposition, Direction
from forex_trader.domain.fundamentals import interpret_fx_text
from forex_trader.domain.macro_history import MacroObservation, PointInTimeFundamentalBook
from forex_trader.domain.models import Quote, TradeCandidate
from forex_trader.domain.sessions import SessionPhase, classify_phase
from forex_trader.domain.strategy import SignalFusionPolicy
from forex_trader.domain.technicals import assess_technicals, pip_size
from forex_trader.research.backtest import BacktestReport, BacktestTrade, OutcomeStatus, summarize_trades
from forex_trader.research.public_history import HistoricalTick, resample_midpoint_candles


class SessionFilter(StrEnum):
    ALL = "all"
    LIQUID = "liquid"
    OPEN_ONLY = "open_only"


class NewsFilter(StrEnum):
    NONE = "none"
    CONFLICT_VETO = "conflict_veto"
    CONFLICT_VETO_COOLDOWN = "conflict_veto_cooldown"


_LIQUID_PHASES = {
    SessionPhase.LONDON_OPEN,
    SessionPhase.NEW_YORK_OPEN,
    SessionPhase.LONDON_NEW_YORK_OVERLAP,
    SessionPhase.LONDON_CONTINUATION,
}
_OPEN_PHASES = {
    SessionPhase.LONDON_OPEN,
    SessionPhase.NEW_YORK_OPEN,
    SessionPhase.LONDON_NEW_YORK_OVERLAP,
}


@dataclass(frozen=True, slots=True)
class TickBacktestOpportunity:
    instrument: str
    decision_time: datetime
    entry_time: datetime
    exit_time: datetime
    trade: BacktestTrade
    technical_score: Decimal
    reward_risk: Decimal
    spread_pips: Decimal
    displacement: bool
    session_phase: SessionPhase
    news_directional: Decimal
    news_confidence: Decimal
    latest_news_age_minutes: Decimal | None
    setup_family: str

    def __post_init__(self) -> None:
        timestamps = (self.decision_time, self.entry_time, self.exit_time)
        if any(value.tzinfo is None for value in timestamps):
            raise ValueError("opportunity timestamps must be timezone-aware")
        if not self.decision_time <= self.entry_time <= self.exit_time:
            raise ValueError("opportunity timestamps must be ordered")
        if self.spread_pips < 0:
            raise ValueError("spread_pips cannot be negative")


@dataclass(frozen=True, slots=True)
class StrategyFilter:
    minimum_score: Decimal
    minimum_reward_risk: Decimal
    maximum_spread_pips: Decimal
    require_displacement: bool
    session_filter: SessionFilter
    news_filter: NewsFilter
    maximum_news_conflict: Decimal = Decimal("0.10")
    minimum_news_confidence: Decimal = Decimal("0.20")
    post_news_cooldown_minutes: int = 10

    def __post_init__(self) -> None:
        if not Decimal("0") <= self.minimum_score <= Decimal("1"):
            raise ValueError("minimum_score must be in [0,1]")
        if self.minimum_reward_risk <= Decimal("1"):
            raise ValueError("minimum_reward_risk must be greater than 1")
        if self.maximum_spread_pips <= 0:
            raise ValueError("maximum_spread_pips must be positive")
        if self.maximum_news_conflict < 0:
            raise ValueError("maximum_news_conflict cannot be negative")
        if not Decimal("0") <= self.minimum_news_confidence <= Decimal("1"):
            raise ValueError("minimum_news_confidence must be in [0,1]")
        if self.post_news_cooldown_minutes < 0:
            raise ValueError("post_news_cooldown_minutes cannot be negative")

    @property
    def identity(self) -> str:
        return (
            f"score={self.minimum_score}|rr={self.minimum_reward_risk}|spread={self.maximum_spread_pips}|"
            f"disp={int(self.require_displacement)}|session={self.session_filter.value}|news={self.news_filter.value}|"
            f"conflict={self.maximum_news_conflict}|news_conf={self.minimum_news_confidence}|"
            f"cooldown={self.post_news_cooldown_minutes}"
        )


@dataclass(frozen=True, slots=True)
class DailyReturnReport:
    risk_fraction_per_trade: Decimal
    total_return: Decimal
    average_daily_return: Decimal
    median_daily_return: Decimal
    best_daily_return: Decimal
    worst_daily_return: Decimal
    profitable_day_fraction: Decimal
    trading_days: int
    maximum_equity_drawdown: Decimal


@dataclass(frozen=True, slots=True)
class SelectionScore:
    strategy_filter: StrategyFilter
    report: BacktestReport
    lower_confidence_expectancy_r: Decimal
    standard_error_r: Decimal


@dataclass(frozen=True, slots=True)
class WalkForwardSelection:
    strategy_filter: StrategyFilter
    calibration_report: BacktestReport
    holdout_report: BacktestReport
    calibration_lower_confidence_expectancy_r: Decimal
    holdout_daily_returns: DailyReturnReport
    calibration_start: datetime
    calibration_end: datetime
    holdout_start: datetime
    holdout_end: datetime
    objective: str


@dataclass(frozen=True, slots=True)
class ExactTickOutcome:
    trade: BacktestTrade
    entry_time: datetime
    exit_time: datetime


def _tick_times(ticks: Sequence[HistoricalTick]) -> list[datetime]:
    return [item.time for item in ticks]


def _first_tick_at_or_after(
    ticks: Sequence[HistoricalTick],
    times: Sequence[datetime],
    instant: datetime,
) -> tuple[int, HistoricalTick] | None:
    index = bisect.bisect_left(times, instant)
    return None if index >= len(ticks) else (index, ticks[index])


def evaluate_candidate_on_ticks(
    candidate: TradeCandidate,
    ticks: Sequence[HistoricalTick],
    *,
    entry_index: int,
    maximum_holding: timedelta = timedelta(hours=2),
    adverse_slippage_pips: Decimal = Decimal("0.10"),
) -> ExactTickOutcome:
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
    elif candidate.direction is Direction.SHORT:
        entry_fill = entry_tick.bid - slippage
    else:
        raise ValueError("flat candidate cannot be backtested")

    long_valid = candidate.stop_loss < entry_fill < candidate.take_profit
    short_valid = candidate.take_profit < entry_fill < candidate.stop_loss
    if (candidate.direction is Direction.LONG and not long_valid) or (
        candidate.direction is Direction.SHORT and not short_valid
    ):
        trade = BacktestTrade(
            candidate.instrument,
            candidate.direction,
            candidate.signal_time,
            candidate.score,
            OutcomeStatus.TIMEOUT,
            Decimal("0"),
            0,
            exit_reason="late_entry_invalid_geometry",
            entry_fill=entry_fill,
            exit_fill=entry_fill,
        )
        return ExactTickOutcome(trade, entry_tick.time, entry_tick.time)

    risk = abs(entry_fill - candidate.stop_loss)
    deadline = entry_tick.time + maximum_holding
    max_favorable = Decimal("0")
    max_adverse = Decimal("0")
    last_tick = entry_tick
    entry_cost_r = slippage / risk

    for tick in ticks[entry_index:]:
        if tick.time > deadline:
            break
        last_tick = tick
        if candidate.direction is Direction.LONG:
            exit_side = tick.bid
            favorable = max(Decimal("0"), (exit_side - entry_fill) / risk)
            adverse = max(Decimal("0"), (entry_fill - exit_side) / risk)
            stop_hit = exit_side <= candidate.stop_loss
            target_hit = exit_side >= candidate.take_profit
        else:
            exit_side = tick.ask
            favorable = max(Decimal("0"), (entry_fill - exit_side) / risk)
            adverse = max(Decimal("0"), (exit_side - entry_fill) / risk)
            stop_hit = exit_side >= candidate.stop_loss
            target_hit = exit_side <= candidate.take_profit
        max_favorable = max(max_favorable, favorable)
        max_adverse = max(max_adverse, adverse)
        if not stop_hit and not target_hit:
            continue

        if candidate.direction is Direction.LONG:
            fill = min(exit_side, candidate.stop_loss) - slippage if stop_hit else candidate.take_profit - slippage
            realized = (fill - entry_fill) / risk
        else:
            fill = max(exit_side, candidate.stop_loss) + slippage if stop_hit else candidate.take_profit + slippage
            realized = (entry_fill - fill) / risk
        bars_held = max(1, math.ceil((tick.time - entry_tick.time).total_seconds() / 300))
        status = OutcomeStatus.LOSS if stop_hit else OutcomeStatus.WIN
        reason = "tick_stop" if stop_hit else "tick_target"
        trade = BacktestTrade(
            candidate.instrument,
            candidate.direction,
            candidate.signal_time,
            candidate.score,
            status,
            realized,
            bars_held,
            exit_reason=reason,
            entry_fill=entry_fill,
            exit_fill=fill,
            maximum_favorable_r=max_favorable,
            maximum_adverse_r=max_adverse,
            estimated_cost_r=entry_cost_r + slippage / risk,
        )
        return ExactTickOutcome(trade, entry_tick.time, tick.time)

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
        exit_reason="tick_time_stop",
        entry_fill=entry_fill,
        exit_fill=exit_fill,
        maximum_favorable_r=max_favorable,
        maximum_adverse_r=max_adverse,
        estimated_cost_r=entry_cost_r + slippage / risk,
    )
    return ExactTickOutcome(trade, entry_tick.time, last_tick.time)


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


def generate_tick_opportunities(
    *,
    instrument: str,
    ticks: Sequence[HistoricalTick],
    fundamentals: PointInTimeFundamentalBook,
    news_observations: Sequence[MacroObservation] = (),
    lower_timeframe: timedelta = timedelta(minutes=5),
    higher_timeframe: timedelta = timedelta(hours=1),
    maximum_holding: timedelta = timedelta(hours=2),
    entry_latency: timedelta = timedelta(milliseconds=500),
    adverse_slippage_pips: Decimal = Decimal("0.10"),
    maximum_decision_quote_age: timedelta = timedelta(seconds=10),
) -> tuple[TickBacktestOpportunity, ...]:
    if len(ticks) < 2:
        return ()
    ordered_ticks = tuple(sorted(ticks, key=lambda item: item.time))
    times = _tick_times(ordered_ticks)
    lower = list(resample_midpoint_candles(ordered_ticks, timeframe=lower_timeframe))
    higher = list(resample_midpoint_candles(ordered_ticks, timeframe=higher_timeframe))
    if len(lower) < 82 or len(higher) < 60:
        return ()

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

    opportunities: list[TickBacktestOpportunity] = []
    for index in range(79, len(lower) - 1):
        signal_candle = lower[index]
        decision_time = signal_candle.time + lower_timeframe
        higher_available = [candle for candle in higher if candle.time + higher_timeframe <= decision_time]
        if len(higher_available) < 60:
            continue

        decision_quote_item = _first_tick_at_or_after(ordered_ticks, times, decision_time)
        if decision_quote_item is None:
            continue
        _, decision_tick = decision_quote_item
        if decision_tick.time - decision_time > maximum_decision_quote_age:
            continue

        technical = assess_technicals(
            normalized,
            lower[max(0, index - 199) : index + 1],
            higher_available[-200:],
            minimum_structural_reward_risk=Decimal("1.01"),
        )
        fundamental = fundamentals.assess_pair(normalized, as_of=decision_time)
        decision_quote = Quote(normalized, decision_tick.bid, decision_tick.ask, decision_tick.time)
        candidate = policy.evaluate(technical, fundamental, decision_quote)
        if candidate.disposition is not DecisionDisposition.TRADE:
            continue

        send_item = _first_tick_at_or_after(ordered_ticks, times, decision_time + entry_latency)
        if send_item is None:
            continue
        entry_index, send_tick = send_item
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
        outcome = evaluate_candidate_on_ticks(
            candidate,
            ordered_ticks,
            entry_index=entry_index,
            maximum_holding=maximum_holding,
            adverse_slippage_pips=adverse_slippage_pips,
        )
        directional_news = fundamental.differential if candidate.direction is Direction.LONG else -fundamental.differential
        opportunities.append(
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
    return tuple(opportunities)


def _session_allowed(phase: SessionPhase, session_filter: SessionFilter) -> bool:
    if session_filter is SessionFilter.ALL:
        return phase is not SessionPhase.ROLLOVER
    if session_filter is SessionFilter.LIQUID:
        return phase in _LIQUID_PHASES
    return phase in _OPEN_PHASES


def _news_allowed(opportunity: TickBacktestOpportunity, strategy_filter: StrategyFilter) -> bool:
    if strategy_filter.news_filter is NewsFilter.NONE:
        return True
    if (
        opportunity.news_confidence >= strategy_filter.minimum_news_confidence
        and opportunity.news_directional < -strategy_filter.maximum_news_conflict
    ):
        return False
    if strategy_filter.news_filter is NewsFilter.CONFLICT_VETO_COOLDOWN:
        age = opportunity.latest_news_age_minutes
        if age is not None and Decimal("0") <= age <= Decimal(strategy_filter.post_news_cooldown_minutes):
            return False
    return True


def filter_opportunities(
    opportunities: Iterable[TickBacktestOpportunity],
    strategy_filter: StrategyFilter,
    *,
    start: datetime | None = None,
    end: datetime | None = None,
) -> tuple[TickBacktestOpportunity, ...]:
    if start is not None and start.tzinfo is None:
        raise ValueError("start must be timezone-aware")
    if end is not None and end.tzinfo is None:
        raise ValueError("end must be timezone-aware")
    selected: list[TickBacktestOpportunity] = []
    available_after: dict[str, datetime] = {}
    for opportunity in sorted(opportunities, key=lambda item: (item.decision_time, item.instrument)):
        if start is not None and opportunity.decision_time < start:
            continue
        if end is not None and opportunity.decision_time >= end:
            continue
        if opportunity.technical_score < strategy_filter.minimum_score:
            continue
        if opportunity.reward_risk < strategy_filter.minimum_reward_risk:
            continue
        if opportunity.spread_pips > strategy_filter.maximum_spread_pips:
            continue
        if strategy_filter.require_displacement and not opportunity.displacement:
            continue
        if not _session_allowed(opportunity.session_phase, strategy_filter.session_filter):
            continue
        if not _news_allowed(opportunity, strategy_filter):
            continue
        if opportunity.entry_time < available_after.get(opportunity.instrument, opportunity.entry_time):
            continue
        selected.append(opportunity)
        available_after[opportunity.instrument] = opportunity.exit_time
    return tuple(selected)


def _selection_score(selected: Sequence[TickBacktestOpportunity], strategy_filter: StrategyFilter) -> SelectionScore:
    report = summarize_trades([item.trade for item in selected])
    if len(selected) < 2:
        return SelectionScore(strategy_filter, report, Decimal("0"), Decimal("999"))
    mean = report.expectancy_r
    variance = sum(((item.trade.r_multiple - mean) ** 2 for item in selected), Decimal("0")) / Decimal(len(selected) - 1)
    standard_error = Decimal(str(math.sqrt(max(0.0, float(variance) / len(selected)))))
    lower = mean - Decimal("1.645") * standard_error
    return SelectionScore(strategy_filter, report, lower, standard_error)


def default_filter_grid() -> tuple[StrategyFilter, ...]:
    grid: list[StrategyFilter] = []
    for score, reward, spread, displacement, session_filter, news_filter in itertools.product(
        (Decimal("0.50"), Decimal("0.55"), Decimal("0.60"), Decimal("0.65"), Decimal("0.70")),
        (Decimal("1.05"), Decimal("1.20"), Decimal("1.35"), Decimal("1.50"), Decimal("1.80")),
        (Decimal("0.8"), Decimal("1.2"), Decimal("1.8"), Decimal("2.5")),
        (False, True),
        tuple(SessionFilter),
        tuple(NewsFilter),
    ):
        grid.append(StrategyFilter(score, reward, spread, displacement, session_filter, news_filter))
    return tuple(grid)


def select_filters_on_calibration(
    opportunities: Sequence[TickBacktestOpportunity],
    *,
    calibration_start: datetime,
    calibration_end: datetime,
    filter_grid: Sequence[StrategyFilter] | None = None,
    minimum_trades: int = 20,
) -> tuple[SelectionScore, SelectionScore]:
    if calibration_start.tzinfo is None or calibration_end.tzinfo is None:
        raise ValueError("calibration boundaries must be timezone-aware")
    if calibration_end <= calibration_start:
        raise ValueError("calibration_end must be after calibration_start")
    if minimum_trades < 2:
        raise ValueError("minimum_trades must be at least two")
    scores: list[SelectionScore] = []
    for strategy_filter in filter_grid or default_filter_grid():
        selected = filter_opportunities(opportunities, strategy_filter, start=calibration_start, end=calibration_end)
        if len(selected) < minimum_trades:
            continue
        score = _selection_score(selected, strategy_filter)
        if score.report.expectancy_r > 0:
            scores.append(score)
    if not scores:
        raise ValueError("no calibration filter produced enough positive-expectancy trades")

    robust = max(
        scores,
        key=lambda item: (
            item.lower_confidence_expectancy_r,
            item.report.expectancy_r,
            item.report.win_rate,
            -item.report.max_drawdown_r,
            item.report.trades,
        ),
    )
    positive_lower = [item for item in scores if item.lower_confidence_expectancy_r > 0]
    win_pool = positive_lower or scores
    win_target = max(
        win_pool,
        key=lambda item: (
            min(item.report.win_rate, Decimal("0.75")),
            item.lower_confidence_expectancy_r,
            item.report.expectancy_r,
            -item.report.max_drawdown_r,
            item.report.trades,
        ),
    )
    return robust, win_target


def simulate_daily_returns(
    opportunities: Iterable[TickBacktestOpportunity],
    *,
    risk_fraction_per_trade: Decimal = Decimal("0.0015"),
    timezone_name: str = "America/New_York",
) -> DailyReturnReport:
    if not Decimal("0") < risk_fraction_per_trade <= Decimal("0.05"):
        raise ValueError("risk_fraction_per_trade must be in (0,0.05]")
    timezone = ZoneInfo(timezone_name)
    equity = Decimal("1")
    peak = equity
    max_drawdown = Decimal("0")
    starts: dict[date, Decimal] = {}
    ends: dict[date, Decimal] = {}
    for opportunity in sorted(opportunities, key=lambda item: (item.exit_time, item.instrument)):
        day = opportunity.exit_time.astimezone(timezone).date()
        starts.setdefault(day, equity)
        equity *= Decimal("1") + risk_fraction_per_trade * opportunity.trade.r_multiple
        ends[day] = equity
        peak = max(peak, equity)
        max_drawdown = max(max_drawdown, (peak - equity) / peak)
    if not ends:
        return DailyReturnReport(
            risk_fraction_per_trade=risk_fraction_per_trade,
            total_return=Decimal("0"),
            average_daily_return=Decimal("0"),
            median_daily_return=Decimal("0"),
            best_daily_return=Decimal("0"),
            worst_daily_return=Decimal("0"),
            profitable_day_fraction=Decimal("0"),
            trading_days=0,
            maximum_equity_drawdown=Decimal("0"),
        )
    returns = sorted(ends[day] / starts[day] - Decimal("1") for day in ends)
    midpoint = len(returns) // 2
    median = returns[midpoint] if len(returns) % 2 else (returns[midpoint - 1] + returns[midpoint]) / Decimal("2")
    return DailyReturnReport(
        risk_fraction_per_trade,
        equity - Decimal("1"),
        sum(returns, Decimal("0")) / Decimal(len(returns)),
        median,
        max(returns),
        min(returns),
        Decimal(sum(value > 0 for value in returns)) / Decimal(len(returns)),
        len(returns),
        max_drawdown,
    )


def evaluate_frozen_filter(
    opportunities: Sequence[TickBacktestOpportunity],
    *,
    selection: SelectionScore,
    calibration_start: datetime,
    calibration_end: datetime,
    holdout_end: datetime,
    objective: str,
    risk_fraction_per_trade: Decimal = Decimal("0.0015"),
) -> WalkForwardSelection:
    calibration = filter_opportunities(opportunities, selection.strategy_filter, start=calibration_start, end=calibration_end)
    holdout = filter_opportunities(opportunities, selection.strategy_filter, start=calibration_end, end=holdout_end)
    return WalkForwardSelection(
        selection.strategy_filter,
        summarize_trades([item.trade for item in calibration]),
        summarize_trades([item.trade for item in holdout]),
        selection.lower_confidence_expectancy_r,
        simulate_daily_returns(holdout, risk_fraction_per_trade=risk_fraction_per_trade),
        calibration_start,
        calibration_end,
        calibration_end,
        holdout_end,
        objective,
    )


def strong_news_observation(observation: MacroObservation) -> bool:
    score, confidence, evidence = interpret_fx_text(f"{observation.headline}. {observation.body}")
    return bool(evidence) and abs(score) >= Decimal("0.50") and confidence >= Decimal("0.35")
