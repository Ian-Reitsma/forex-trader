from __future__ import annotations

from decimal import Decimal

import pytest

from forex_trader.research.runtime_management_sweep import (
    RuntimeManagementSweepPoint,
    chronological_holdout_split,
    default_runtime_management_grid,
    rank_sweep_results,
)


def test_default_runtime_management_grid_is_bounded_and_contains_current_policy() -> None:
    grid = default_runtime_management_grid()
    assert len(grid) == 342
    assert len(set(grid)) == len(grid)
    assert all(point.progress_check_minutes < point.maximum_holding_minutes for point in grid)
    assert RuntimeManagementSweepPoint(
        progress_check_minutes=30,
        minimum_progress_r=Decimal("0.15"),
        maximum_holding_minutes=120,
        break_even_after_r=Decimal("1.00"),
    ) in grid


def test_sweep_point_builds_runtime_policy() -> None:
    point = RuntimeManagementSweepPoint(
        progress_check_minutes=20,
        minimum_progress_r=Decimal("0.10"),
        maximum_holding_minutes=90,
        break_even_after_r=Decimal("0.75"),
    )
    policy = point.policy()
    assert int(policy.progress_check_after.total_seconds() // 60) == 20
    assert policy.minimum_progress_r == Decimal("0.10")
    assert int(policy.maximum_holding_time.total_seconds() // 60) == 90
    assert policy.break_even_after_r == Decimal("0.75")


def test_chronological_holdout_split_preserves_order() -> None:
    train, holdout = chronological_holdout_split(tuple(range(8)), train_fraction=Decimal("0.625"))
    assert train == (0, 1, 2, 3, 4)
    assert holdout == (5, 6, 7)


def test_chronological_holdout_split_rejects_invalid_inputs() -> None:
    with pytest.raises(ValueError, match="at least four"):
        chronological_holdout_split((1, 2, 3))
    with pytest.raises(ValueError, match="train_fraction"):
        chronological_holdout_split((1, 2, 3, 4), train_fraction=Decimal("1"))


def test_rank_sweep_results_prefers_expectancy_then_total_then_drawdown() -> None:
    rows = [
        {"expectancy_r": "0.10", "total_r": "1.0", "max_drawdown_r": "0.9"},
        {"expectancy_r": "0.20", "total_r": "0.5", "max_drawdown_r": "2.0"},
        {"expectancy_r": "0.20", "total_r": "0.5", "max_drawdown_r": "1.0"},
    ]
    ranked = rank_sweep_results(rows)
    assert ranked[0] is rows[2]
    assert ranked[1] is rows[1]
    assert ranked[2] is rows[0]
