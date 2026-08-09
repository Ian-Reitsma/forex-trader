from __future__ import annotations

import heapq
import itertools
import math
from collections import deque
from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Iterable, Sequence

from forex_trader.domain.enums import Direction
from forex_trader.research.backtest import BacktestReport, summarize_trades
from forex_trader.research.tick_backtest import (
    NewsFilter,
    SessionFilter,
    StrategyFilter,
    TickBacktestOpportunity,
    filter_opportunities,
)


@dataclass(frozen=True, slots=True)
class ManagedCohortPolicy:
    strategy_filter: StrategyFilter
    take_profit_r: Decimal
    instrument: str | None = None
    direction: Direction | None = None

    def __post_init__(self) -> None:
        if not Decimal("0") < self.take_profit_r <= Decimal("1"):
            raise ValueError("take_profit_r must be in (0,1]")
        if self.instrument is not None and "_" not in self.instrument:
            raise ValueError("instrument must use broker form such as EUR_USD")
        if self.direction is Direction.FLAT:
            raise ValueError("adaptive cohort direction cannot be flat")

    @property
    def identity(self) -> str:
        return (
            f"{self.strategy_filter.identity}|tp={self.take_profit_r}|"
            f"instrument={self.instrument or 'ALL'}|direction={self.direction.value if self.direction else 'ALL'}"
        )


@dataclass(frozen=True, slots=True)
class ShadowRegimeGate:
    lookback: int
    minimum_samples: int
    minimum_economic_win_rate: Decimal
    minimum_expectancy_r: Decimal

    def __post_init__(self) -> None:
        if self.lookback < 3:
            raise ValueError("lookback must be at least three")
        if not 2 <= self.minimum_samples <= self.lookback:
            raise ValueError("minimum_samples must be in [2, lookback]")
        if not Decimal("0") <= self.minimum_economic_win_rate <= Decimal("1"):
            raise ValueError("minimum_economic_win_rate must be in [0,1]")

    @property
    def identity(self) -> str:
        return (
            f"lookback={self.lookback}|min_samples={self.minimum_samples}|"
            f"min_win={self.minimum_economic_win_rate}|min_exp={self.minimum_expectancy_r}"
        )


@dataclass(frozen=True, slots=True)
class AdaptiveManagedPolicy:
    cohort: ManagedCohortPolicy
    gate: ShadowRegimeGate

    @property
    def identity(self) -> str:
        return f"{self.cohort.identity}|{self.gate.identity}"


@dataclass(frozen=True, slots=True)
class AdaptivePolicyReport:
    policy: AdaptiveManagedPolicy
    report: BacktestReport
    economic_wins: int
    economic_win_rate: Decimal
    lower_confidence_expectancy_r: Decimal
    fold_expectancies: tuple[Decimal, ...]
    fold_economic_win_rates: tuple[Decimal, ...]
    fold_trade_counts: tuple[int, ...]


def compact_strategy_filter_grid() -> tuple[StrategyFilter, ...]:
    filters: list[StrategyFilter] = []
    for score, rr, spread, displacement, session_filter in itertools.product(
        (Decimal("0.45"), Decimal("0.50"), Decimal("0.55"), Decimal("0.60"), Decimal("0.65")),
        (Decimal("1.05"), Decimal("1.20"), Decimal("1.35")),
        (Decimal("0.6"), Decimal("0.8"), Decimal("1.2")),
        (False, True),
        (SessionFilter.LIQUID, SessionFilter.OPEN_ONLY),
    ):
        filters.append(
            StrategyFilter(
                minimum_score=score,
                minimum_reward_risk=rr,
                maximum_spread_pips=spread,
                require_displacement=displacement,
                session_filter=session_filter,
                news_filter=NewsFilter.NONE,
            )
        )
    return tuple(filters)


def default_shadow_gate_grid() -> tuple[ShadowRegimeGate, ...]:
    gates: list[ShadowRegimeGate] = []
    for lookback, samples in ((6, 4), (10, 6), (16, 8)):
        for minimum_win, minimum_expectancy in itertools.product(
            (Decimal("0.50"), Decimal("0.60"), Decimal("0.70")),
            (Decimal("-0.05"), Decimal("0"), Decimal("0.05")),
        ):
            gates.append(ShadowRegimeGate(lookback, samples, minimum_win, minimum_expectancy))
    return tuple(gates)


def _cohort_source(
    opportunities: Iterable[TickBacktestOpportunity],
    policy: ManagedCohortPolicy,
    *,
    start: datetime,
    end: datetime,
) -> tuple[TickBacktestOpportunity, ...]:
    source = tuple(opportunities)
    if policy.instrument is not None:
        source = tuple(item for item in source if item.instrument == policy.instrument)
    if policy.direction is not None:
        source = tuple(item for item in source if item.trade.direction is policy.direction)
    return filter_opportunities(source, policy.strategy_filter, start=start, end=end)


def economic_win_rate(opportunities: Sequence[TickBacktestOpportunity]) -> Decimal:
    if not opportunities:
        return Decimal("0")
    return Decimal(sum(item.trade.r_multiple > 0 for item in opportunities)) / Decimal(len(opportunities))


def _expectancy(opportunities: Sequence[TickBacktestOpportunity]) -> Decimal:
    if not opportunities:
        return Decimal("0")
    return sum((item.trade.r_multiple for item in opportunities), Decimal("0")) / Decimal(len(opportunities))


def apply_shadow_regime_gate(
    opportunities: Sequence[TickBacktestOpportunity],
    gate: ShadowRegimeGate,
    *,
    evaluation_start: datetime,
    evaluation_end: datetime,
) -> tuple[TickBacktestOpportunity, ...]:
    """Trade only while recently completed *shadow* setups retain edge.

    Every base-policy opportunity is evaluated in shadow even when capital is gated off.
    Only outcomes whose exit timestamp is at or before the current decision are admitted to
    the rolling regime state. This makes the gate causal while still allowing it to recover
    from a stand-down period, as the live system can continue scoring virtual candidates.
    """
    if evaluation_start.tzinfo is None or evaluation_end.tzinfo is None:
        raise ValueError("evaluation boundaries must be timezone-aware")
    if evaluation_end <= evaluation_start:
        raise ValueError("evaluation_end must be after evaluation_start")

    ordered = tuple(sorted(opportunities, key=lambda item: (item.decision_time, item.instrument)))
    pending: list[tuple[datetime, int, TickBacktestOpportunity]] = []
    completed: deque[TickBacktestOpportunity] = deque(maxlen=gate.lookback)
    selected: list[TickBacktestOpportunity] = []
    serial = 0

    for opportunity in ordered:
        while pending and pending[0][0] <= opportunity.decision_time:
            _, _, matured = heapq.heappop(pending)
            completed.append(matured)

        if evaluation_start <= opportunity.decision_time < evaluation_end and len(completed) >= gate.minimum_samples:
            sample = tuple(completed)
            if (
                economic_win_rate(sample) >= gate.minimum_economic_win_rate
                and _expectancy(sample) >= gate.minimum_expectancy_r
            ):
                selected.append(opportunity)

        heapq.heappush(pending, (opportunity.exit_time, serial, opportunity))
        serial += 1

    return tuple(selected)


def _fold_boundaries(start: datetime, end: datetime, folds: int = 3) -> tuple[tuple[datetime, datetime], ...]:
    if folds < 2:
        raise ValueError("folds must be at least two")
    duration = end - start
    boundaries: list[tuple[datetime, datetime]] = []
    for index in range(folds):
        left = start + duration * index / folds
        right = end if index + 1 == folds else start + duration * (index + 1) / folds
        boundaries.append((left, right))
    return tuple(boundaries)


def _lower_confidence_expectancy(opportunities: Sequence[TickBacktestOpportunity]) -> Decimal:
    if len(opportunities) < 2:
        return Decimal("-999")
    mean = _expectancy(opportunities)
    variance = sum(
        ((item.trade.r_multiple - mean) ** 2 for item in opportunities),
        Decimal("0"),
    ) / Decimal(len(opportunities) - 1)
    standard_error = Decimal(str(math.sqrt(max(0.0, float(variance) / len(opportunities)))))
    return mean - Decimal("1.645") * standard_error


def _policy_report(
    policy: AdaptiveManagedPolicy,
    base: Sequence[TickBacktestOpportunity],
    *,
    development_start: datetime,
    development_end: datetime,
) -> AdaptivePolicyReport:
    selected = apply_shadow_regime_gate(
        base,
        policy.gate,
        evaluation_start=development_start,
        evaluation_end=development_end,
    )
    fold_expectancies: list[Decimal] = []
    fold_win_rates: list[Decimal] = []
    fold_counts: list[int] = []
    for fold_start, fold_end in _fold_boundaries(development_start, development_end):
        fold = tuple(item for item in selected if fold_start <= item.decision_time < fold_end)
        fold_expectancies.append(_expectancy(fold))
        fold_win_rates.append(economic_win_rate(fold))
        fold_counts.append(len(fold))
    return AdaptivePolicyReport(
        policy=policy,
        report=summarize_trades([item.trade for item in selected]),
        economic_wins=sum(item.trade.r_multiple > 0 for item in selected),
        economic_win_rate=economic_win_rate(selected),
        lower_confidence_expectancy_r=_lower_confidence_expectancy(selected),
        fold_expectancies=tuple(fold_expectancies),
        fold_economic_win_rates=tuple(fold_win_rates),
        fold_trade_counts=tuple(fold_counts),
    )


def select_stable_adaptive_policies(
    opportunities_by_target: dict[Decimal, Sequence[TickBacktestOpportunity]],
    *,
    development_start: datetime,
    development_end: datetime,
    instruments: Sequence[str],
    minimum_total_trades: int = 24,
    minimum_fold_trades: int = 4,
    entry_filters: Sequence[StrategyFilter] | None = None,
    gates: Sequence[ShadowRegimeGate] | None = None,
    top_base_candidates: int = 36,
) -> tuple[AdaptivePolicyReport, AdaptivePolicyReport]:
    """Select robust and win-target policies using only known development history.

    Static cohort candidates are first screened for multi-fold stability. Adaptive shadow
    gates are then fitted only on the best stable base cohorts. A policy must remain
    positive overall and positive in at least two of three development folds.
    """
    if development_start.tzinfo is None or development_end.tzinfo is None:
        raise ValueError("development boundaries must be timezone-aware")
    if development_end <= development_start:
        raise ValueError("development_end must be after development_start")
    if minimum_total_trades < 6 or minimum_fold_trades < 2:
        raise ValueError("development sample floors are too small")

    filters = tuple(entry_filters or compact_strategy_filter_grid())
    gate_grid = tuple(gates or default_shadow_gate_grid())
    cohort_selectors: tuple[tuple[str | None, Direction | None], ...] = (
        (None, None),
        *((instrument, None) for instrument in instruments),
        (None, Direction.LONG),
        (None, Direction.SHORT),
    )
    base_ranked: list[tuple[tuple[Decimal, ...], ManagedCohortPolicy, tuple[TickBacktestOpportunity, ...]]] = []
    folds = _fold_boundaries(development_start, development_end)

    for target, target_opportunities in sorted(opportunities_by_target.items()):
        for strategy_filter in filters:
            for instrument, direction in cohort_selectors:
                cohort = ManagedCohortPolicy(strategy_filter, target, instrument, direction)
                base = _cohort_source(
                    target_opportunities,
                    cohort,
                    start=development_start,
                    end=development_end,
                )
                if len(base) < minimum_total_trades:
                    continue
                fold_values: list[tuple[int, Decimal, Decimal]] = []
                for fold_start, fold_end in folds:
                    fold = tuple(item for item in base if fold_start <= item.decision_time < fold_end)
                    fold_values.append((len(fold), _expectancy(fold), economic_win_rate(fold)))
                if min(value[0] for value in fold_values) < minimum_fold_trades:
                    continue
                if _expectancy(base) <= 0:
                    continue
                positive_folds = sum(value[1] > 0 for value in fold_values)
                if positive_folds < 2:
                    continue
                rank = (
                    Decimal(positive_folds),
                    min(value[1] for value in fold_values),
                    min(value[2] for value in fold_values),
                    _expectancy(base),
                    economic_win_rate(base),
                    Decimal(len(base)),
                )
                base_ranked.append((rank, cohort, base))

    if not base_ranked:
        raise ValueError("no base cohort survived multi-fold stability screening")
    base_ranked.sort(key=lambda item: item[0], reverse=True)

    reports: list[AdaptivePolicyReport] = []
    for _, cohort, base in base_ranked[:top_base_candidates]:
        for gate in gate_grid:
            report = _policy_report(
                AdaptiveManagedPolicy(cohort, gate),
                base,
                development_start=development_start,
                development_end=development_end,
            )
            if report.report.trades < minimum_total_trades:
                continue
            if min(report.fold_trade_counts) < minimum_fold_trades:
                continue
            if report.report.expectancy_r <= 0:
                continue
            if sum(value > 0 for value in report.fold_expectancies) < 2:
                continue
            reports.append(report)

    if not reports:
        raise ValueError("no adaptive policy survived development stability requirements")

    robust = max(
        reports,
        key=lambda item: (
            item.lower_confidence_expectancy_r,
            min(item.fold_expectancies),
            item.report.expectancy_r,
            min(item.fold_economic_win_rates),
            item.economic_win_rate,
            -item.report.max_drawdown_r,
            item.report.trades,
        ),
    )
    positive_lower = [item for item in reports if item.lower_confidence_expectancy_r > 0]
    win_pool = positive_lower or reports
    win_target = max(
        win_pool,
        key=lambda item: (
            min(item.economic_win_rate, Decimal("0.75")),
            min(item.fold_economic_win_rates),
            item.lower_confidence_expectancy_r,
            min(item.fold_expectancies),
            item.report.expectancy_r,
            -item.report.max_drawdown_r,
        ),
    )
    return robust, win_target


def evaluate_frozen_adaptive_policy(
    opportunities_by_target: dict[Decimal, Sequence[TickBacktestOpportunity]],
    *,
    policy_report: AdaptivePolicyReport,
    history_start: datetime,
    evaluation_start: datetime,
    evaluation_end: datetime,
) -> tuple[tuple[TickBacktestOpportunity, ...], BacktestReport, Decimal]:
    policy = policy_report.policy
    source = _cohort_source(
        opportunities_by_target[policy.cohort.take_profit_r],
        policy.cohort,
        start=history_start,
        end=evaluation_end,
    )
    selected = apply_shadow_regime_gate(
        source,
        policy.gate,
        evaluation_start=evaluation_start,
        evaluation_end=evaluation_end,
    )
    return selected, summarize_trades([item.trade for item in selected]), economic_win_rate(selected)
