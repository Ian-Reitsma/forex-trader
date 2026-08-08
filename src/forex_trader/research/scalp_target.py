from __future__ import annotations

import itertools
import math
from dataclasses import dataclass, replace
from datetime import datetime
from decimal import Decimal
from typing import Iterable, Sequence

from forex_trader.research.backtest import BacktestReport, BacktestTrade, OutcomeStatus, summarize_trades
from forex_trader.research.tick_backtest import (
    NewsFilter,
    SessionFilter,
    StrategyFilter,
    TickBacktestOpportunity,
    filter_opportunities,
    simulate_daily_returns,
)


@dataclass(frozen=True, slots=True)
class ScalpTargetPolicy:
    """Entry filter plus a profit target expressed in structural-risk units."""

    entry_filter: StrategyFilter
    target_r: Decimal
    instrument: str | None = None

    def __post_init__(self) -> None:
        if not Decimal("0") < self.target_r <= Decimal("1"):
            raise ValueError("target_r must be in (0,1]")
        if self.instrument is not None and "_" not in self.instrument:
            raise ValueError("instrument must use broker form such as EUR_USD")

    @property
    def identity(self) -> str:
        instrument = self.instrument or "ALL"
        return f"{self.entry_filter.identity}|target_r={self.target_r}|instrument={instrument}"


@dataclass(frozen=True, slots=True)
class ScalpTargetReport:
    policy: ScalpTargetPolicy
    report: BacktestReport
    economic_wins: int
    economic_win_rate: Decimal
    lower_confidence_expectancy_r: Decimal
    expectancy_standard_error_r: Decimal


@dataclass(frozen=True, slots=True)
class FrozenScalpTargetResult:
    policy: ScalpTargetPolicy
    development: ScalpTargetReport
    holdout: ScalpTargetReport
    development_start: datetime
    development_end: datetime
    holdout_end: datetime
    objective: str
    holdout_daily_returns: object


def _target_fill_trade(trade: BacktestTrade, target_r: Decimal) -> BacktestTrade:
    """Retarget an exact-path trade when its recorded MFE proves the target was touched.

    Exact tick evaluation updates MFE chronologically and stops as soon as the original
    structural stop/target fires. Therefore MFE >= a smaller target proves that smaller
    target was reached before any later structural stop. Entry and exit slippage are
    symmetric in the tick campaign, so half the recorded two-sided slippage cost is
    charged to the target exit.
    """
    if trade.maximum_favorable_r < target_r:
        return trade
    exit_slippage_r = trade.estimated_cost_r / Decimal("2")
    realized = target_r - exit_slippage_r
    return replace(
        trade,
        status=OutcomeStatus.WIN if realized > 0 else OutcomeStatus.LOSS,
        r_multiple=realized,
        exit_reason=f"scalp_target_{target_r}",
    )


def apply_scalp_target(
    opportunities: Iterable[TickBacktestOpportunity],
    policy: ScalpTargetPolicy,
    *,
    start: datetime | None = None,
    end: datetime | None = None,
) -> tuple[TickBacktestOpportunity, ...]:
    base = tuple(opportunities)
    if policy.instrument is not None:
        base = tuple(item for item in base if item.instrument == policy.instrument)
    filtered = filter_opportunities(base, policy.entry_filter, start=start, end=end)
    transformed: list[TickBacktestOpportunity] = []
    for opportunity in filtered:
        if opportunity.reward_risk < policy.target_r:
            continue
        transformed.append(replace(opportunity, trade=_target_fill_trade(opportunity.trade, policy.target_r)))
    return tuple(transformed)


def summarize_scalp_target(
    opportunities: Sequence[TickBacktestOpportunity],
    policy: ScalpTargetPolicy,
) -> ScalpTargetReport:
    report = summarize_trades([item.trade for item in opportunities])
    economic_wins = sum(item.trade.r_multiple > 0 for item in opportunities)
    economic_win_rate = (
        Decimal(economic_wins) / Decimal(len(opportunities)) if opportunities else Decimal("0")
    )
    if len(opportunities) < 2:
        return ScalpTargetReport(
            policy,
            report,
            economic_wins,
            economic_win_rate,
            Decimal("-999"),
            Decimal("999"),
        )
    mean = report.expectancy_r
    variance = sum(
        ((item.trade.r_multiple - mean) ** 2 for item in opportunities),
        Decimal("0"),
    ) / Decimal(len(opportunities) - 1)
    standard_error = Decimal(str(math.sqrt(max(0.0, float(variance) / len(opportunities)))))
    lower = mean - Decimal("1.645") * standard_error
    return ScalpTargetReport(
        policy,
        report,
        economic_wins,
        economic_win_rate,
        lower,
        standard_error,
    )


def default_scalp_policy_grid(
    instruments: Sequence[str],
) -> tuple[ScalpTargetPolicy, ...]:
    policies: list[ScalpTargetPolicy] = []
    instrument_filters: tuple[str | None, ...] = (None, *tuple(instruments))
    for (
        score,
        spread,
        displacement,
        session_filter,
        target_r,
        instrument,
    ) in itertools.product(
        (
            Decimal("0.45"),
            Decimal("0.50"),
            Decimal("0.55"),
            Decimal("0.60"),
            Decimal("0.65"),
            Decimal("0.70"),
        ),
        (Decimal("0.6"), Decimal("0.8"), Decimal("1.2"), Decimal("1.8")),
        (False, True),
        tuple(SessionFilter),
        (
            Decimal("0.25"),
            Decimal("0.33"),
            Decimal("0.40"),
            Decimal("0.50"),
            Decimal("0.65"),
            Decimal("0.80"),
        ),
        instrument_filters,
    ):
        entry_filter = StrategyFilter(
            minimum_score=score,
            minimum_reward_risk=Decimal("1.01"),
            maximum_spread_pips=spread,
            require_displacement=displacement,
            session_filter=session_filter,
            news_filter=NewsFilter.NONE,
        )
        policies.append(ScalpTargetPolicy(entry_filter, target_r, instrument))
    return tuple(policies)


def select_scalp_target_policy(
    opportunities: Sequence[TickBacktestOpportunity],
    *,
    development_start: datetime,
    development_end: datetime,
    instruments: Sequence[str],
    minimum_trades: int = 30,
    policy_grid: Sequence[ScalpTargetPolicy] | None = None,
) -> tuple[ScalpTargetReport, ScalpTargetReport]:
    if development_start.tzinfo is None or development_end.tzinfo is None:
        raise ValueError("development boundaries must be timezone-aware")
    if development_end <= development_start:
        raise ValueError("development_end must be after development_start")
    if minimum_trades < 10:
        raise ValueError("minimum_trades must be at least ten")
    reports: list[ScalpTargetReport] = []
    for policy in policy_grid or default_scalp_policy_grid(instruments):
        selected = apply_scalp_target(
            opportunities,
            policy,
            start=development_start,
            end=development_end,
        )
        if len(selected) < minimum_trades:
            continue
        report = summarize_scalp_target(selected, policy)
        if report.report.expectancy_r > 0:
            reports.append(report)
    if not reports:
        raise ValueError("no scalp target policy produced enough positive-expectancy development trades")

    robust = max(
        reports,
        key=lambda item: (
            item.lower_confidence_expectancy_r,
            item.report.expectancy_r,
            item.economic_win_rate,
            -item.report.max_drawdown_r,
            item.report.trades,
        ),
    )
    positive_lower = [item for item in reports if item.lower_confidence_expectancy_r > 0]
    goal_pool = positive_lower or reports
    win_target = max(
        goal_pool,
        key=lambda item: (
            min(item.economic_win_rate, Decimal("0.75")),
            item.lower_confidence_expectancy_r,
            item.report.expectancy_r,
            -item.report.max_drawdown_r,
            item.report.trades,
        ),
    )
    return robust, win_target


def evaluate_frozen_scalp_target(
    opportunities: Sequence[TickBacktestOpportunity],
    *,
    selection: ScalpTargetReport,
    development_start: datetime,
    development_end: datetime,
    holdout_end: datetime,
    objective: str,
    risk_fraction_per_trade: Decimal = Decimal("0.0015"),
) -> FrozenScalpTargetResult:
    development_trades = apply_scalp_target(
        opportunities,
        selection.policy,
        start=development_start,
        end=development_end,
    )
    holdout_trades = apply_scalp_target(
        opportunities,
        selection.policy,
        start=development_end,
        end=holdout_end,
    )
    return FrozenScalpTargetResult(
        policy=selection.policy,
        development=summarize_scalp_target(development_trades, selection.policy),
        holdout=summarize_scalp_target(holdout_trades, selection.policy),
        development_start=development_start,
        development_end=development_end,
        holdout_end=holdout_end,
        objective=objective,
        holdout_daily_returns=simulate_daily_returns(
            holdout_trades,
            risk_fraction_per_trade=risk_fraction_per_trade,
        ),
    )
