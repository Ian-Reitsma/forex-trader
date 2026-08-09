from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Sequence

from forex_trader.domain.enums import Direction
from forex_trader.research.adaptive_managed_strategy import (
    ShadowRegimeGate,
    apply_shadow_regime_gate,
    compact_strategy_filter_grid,
    default_shadow_gate_grid,
    economic_win_rate,
)
from forex_trader.research.backtest import BacktestReport, summarize_trades
from forex_trader.research.partial_runner_backtest import PartialRunnerProfile
from forex_trader.research.tick_backtest import StrategyFilter, TickBacktestOpportunity, filter_opportunities


@dataclass(frozen=True, slots=True)
class PartialRunnerPolicyScore:
    profile: PartialRunnerProfile
    strategy_filter: StrategyFilter
    gate: ShadowRegimeGate
    instrument: str | None
    direction: Direction | None
    report: BacktestReport
    economic_win_rate: Decimal
    lower_confidence_expectancy_r: Decimal
    fold_expectancies: tuple[Decimal, ...]
    fold_economic_win_rates: tuple[Decimal, ...]
    fold_trade_counts: tuple[int, ...]

    @property
    def identity(self) -> str:
        return (
            f"{self.profile.identity}|{self.strategy_filter.identity}|{self.gate.identity}|"
            f"instrument={self.instrument or 'ALL'}|direction={self.direction.value if self.direction else 'ALL'}"
        )


def _expectancy(values: Sequence[TickBacktestOpportunity]) -> Decimal:
    if not values:
        return Decimal("0")
    return sum((item.trade.r_multiple for item in values), Decimal("0")) / Decimal(len(values))


def _lower_confidence(values: Sequence[TickBacktestOpportunity]) -> Decimal:
    if len(values) < 2:
        return Decimal("-999")
    mean = _expectancy(values)
    variance = sum(((item.trade.r_multiple - mean) ** 2 for item in values), Decimal("0")) / Decimal(len(values) - 1)
    standard_error = Decimal(str(math.sqrt(max(0.0, float(variance) / len(values)))))
    return mean - Decimal("1.645") * standard_error


def _folds(start: datetime, end: datetime) -> tuple[tuple[datetime, datetime], ...]:
    duration = end - start
    return (
        (start, start + duration / 3),
        (start + duration / 3, start + duration * 2 / 3),
        (start + duration * 2 / 3, end),
    )


def _cohort(
    opportunities: Sequence[TickBacktestOpportunity],
    *,
    strategy_filter: StrategyFilter,
    instrument: str | None,
    direction: Direction | None,
    start: datetime,
    end: datetime,
) -> tuple[TickBacktestOpportunity, ...]:
    values = opportunities
    if instrument is not None:
        values = tuple(item for item in values if item.instrument == instrument)
    if direction is not None:
        values = tuple(item for item in values if item.trade.direction is direction)
    return filter_opportunities(values, strategy_filter, start=start, end=end)


def select_stable_partial_runner_policies(
    opportunities_by_profile: dict[PartialRunnerProfile, Sequence[TickBacktestOpportunity]],
    *,
    development_start: datetime,
    development_end: datetime,
    instruments: Sequence[str],
    minimum_total_trades: int = 30,
    minimum_fold_trades: int = 5,
    entry_filters: Sequence[StrategyFilter] | None = None,
    gates: Sequence[ShadowRegimeGate] | None = None,
    top_base_candidates: int = 30,
) -> tuple[PartialRunnerPolicyScore, PartialRunnerPolicyScore]:
    if development_start.tzinfo is None or development_end.tzinfo is None:
        raise ValueError("development boundaries must be timezone-aware")
    if development_end <= development_start:
        raise ValueError("development_end must be after development_start")
    if minimum_total_trades < 12 or minimum_fold_trades < 3:
        raise ValueError("development sample floors are too small")

    filters = tuple(entry_filters or compact_strategy_filter_grid())
    gate_grid = tuple(gates or default_shadow_gate_grid())
    selectors: tuple[tuple[str | None, Direction | None], ...] = (
        (None, None),
        *((instrument, None) for instrument in instruments),
        (None, Direction.LONG),
        (None, Direction.SHORT),
    )
    folds = _folds(development_start, development_end)
    bases: list[
        tuple[
            tuple[Decimal, ...],
            PartialRunnerProfile,
            StrategyFilter,
            str | None,
            Direction | None,
            tuple[TickBacktestOpportunity, ...],
        ]
    ] = []

    for profile, opportunities in sorted(opportunities_by_profile.items()):
        for strategy_filter in filters:
            for instrument, direction in selectors:
                base = _cohort(
                    opportunities,
                    strategy_filter=strategy_filter,
                    instrument=instrument,
                    direction=direction,
                    start=development_start,
                    end=development_end,
                )
                if len(base) < minimum_total_trades or _expectancy(base) <= 0:
                    continue
                fold_values: list[tuple[int, Decimal, Decimal]] = []
                for left, right in folds:
                    fold = tuple(item for item in base if left <= item.decision_time < right)
                    fold_values.append((len(fold), _expectancy(fold), economic_win_rate(fold)))
                if min(item[0] for item in fold_values) < minimum_fold_trades:
                    continue
                positive_folds = sum(item[1] > 0 for item in fold_values)
                if positive_folds < 2:
                    continue
                rank = (
                    Decimal(positive_folds),
                    min(item[1] for item in fold_values),
                    min(item[2] for item in fold_values),
                    _expectancy(base),
                    economic_win_rate(base),
                    Decimal(len(base)),
                )
                bases.append((rank, profile, strategy_filter, instrument, direction, base))

    if not bases:
        raise ValueError("no partial-runner base policy survived multi-fold stability screening")
    bases.sort(key=lambda item: item[0], reverse=True)

    scores: list[PartialRunnerPolicyScore] = []
    for _, profile, strategy_filter, instrument, direction, base in bases[:top_base_candidates]:
        for gate in gate_grid:
            selected = apply_shadow_regime_gate(
                base,
                gate,
                evaluation_start=development_start,
                evaluation_end=development_end,
            )
            if len(selected) < minimum_total_trades or _expectancy(selected) <= 0:
                continue
            fold_expectancies: list[Decimal] = []
            fold_wins: list[Decimal] = []
            fold_counts: list[int] = []
            for left, right in folds:
                fold = tuple(item for item in selected if left <= item.decision_time < right)
                fold_expectancies.append(_expectancy(fold))
                fold_wins.append(economic_win_rate(fold))
                fold_counts.append(len(fold))
            if min(fold_counts) < minimum_fold_trades:
                continue
            if sum(value > 0 for value in fold_expectancies) < 2:
                continue
            report = summarize_trades([item.trade for item in selected])
            scores.append(
                PartialRunnerPolicyScore(
                    profile=profile,
                    strategy_filter=strategy_filter,
                    gate=gate,
                    instrument=instrument,
                    direction=direction,
                    report=report,
                    economic_win_rate=economic_win_rate(selected),
                    lower_confidence_expectancy_r=_lower_confidence(selected),
                    fold_expectancies=tuple(fold_expectancies),
                    fold_economic_win_rates=tuple(fold_wins),
                    fold_trade_counts=tuple(fold_counts),
                )
            )

    if not scores:
        raise ValueError("no partial-runner policy survived adaptive stability screening")

    robust = max(
        scores,
        key=lambda item: (
            item.lower_confidence_expectancy_r,
            min(item.fold_expectancies),
            item.report.expectancy_r,
            min(item.fold_economic_win_rates),
            item.economic_win_rate,
            -item.report.max_drawdown_r,
        ),
    )
    positive_lower = [item for item in scores if item.lower_confidence_expectancy_r > 0]
    win_pool = positive_lower or scores
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
