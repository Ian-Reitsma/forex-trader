from __future__ import annotations

import math
from dataclasses import dataclass
from decimal import Decimal
from typing import Iterable

from forex_trader.research.backtest import BacktestReport, BacktestTrade, summarize_trades


@dataclass(frozen=True, slots=True)
class RobustThresholdScore:
    threshold: Decimal
    report: BacktestReport
    standard_error_r: Decimal
    lower_confidence_expectancy_r: Decimal


def confidence_adjusted_thresholds(
    trades: Iterable[BacktestTrade],
    *,
    thresholds: tuple[Decimal, ...],
    minimum_trades: int = 30,
    confidence_z: Decimal = Decimal("1.96"),
) -> tuple[RobustThresholdScore, ...]:
    sample = tuple(trades)
    if minimum_trades < 2:
        raise ValueError("minimum_trades must be at least 2")
    if confidence_z < 0:
        raise ValueError("confidence_z cannot be negative")
    results: list[RobustThresholdScore] = []
    for threshold in thresholds:
        selected = [item for item in sample if item.score >= threshold]
        if len(selected) < minimum_trades:
            continue
        report = summarize_trades(selected, minimum_score=threshold)
        mean = report.expectancy_r
        variance = sum(((item.r_multiple - mean) ** 2 for item in selected), Decimal("0")) / Decimal(len(selected) - 1)
        standard_error = Decimal(str(math.sqrt(float(variance) / len(selected))))
        lower = mean - confidence_z * standard_error
        results.append(RobustThresholdScore(threshold, report, standard_error, lower))
    return tuple(results)


def select_confidence_adjusted_threshold(
    trades: Iterable[BacktestTrade],
    *,
    thresholds: tuple[Decimal, ...],
    minimum_trades: int = 30,
    confidence_z: Decimal = Decimal("1.96"),
) -> RobustThresholdScore:
    results = confidence_adjusted_thresholds(
        trades,
        thresholds=thresholds,
        minimum_trades=minimum_trades,
        confidence_z=confidence_z,
    )
    if not results:
        raise ValueError("no threshold has enough trades for confidence-adjusted selection")
    return max(
        results,
        key=lambda item: (
            item.lower_confidence_expectancy_r,
            item.report.expectancy_r,
            -item.report.max_drawdown_r,
            -item.report.average_cost_r,
            item.report.trades,
        ),
    )
