from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Sequence

from forex_trader.domain.enums import Direction
from forex_trader.research.adaptive_managed_strategy import ShadowRegimeGate, apply_shadow_regime_gate
from forex_trader.research.partial_runner_backtest import PartialRunnerProfile
from forex_trader.research.tick_backtest import (
    NewsFilter,
    SessionFilter,
    StrategyFilter,
    TickBacktestOpportunity,
    filter_opportunities,
)


# Frozen from the 2026-05-20 -> 2026-08-07 development artifact produced by
# partial-runner-research-v0.7.28 at ed8b7da024957430eebae3c1088446084b0cd6b6.
# These values MUST NOT be selected or modified from the sealed validation tape.
FROZEN_PARTIAL_RUNNER_PROFILE = PartialRunnerProfile(
    first_target_r=Decimal("0.50"),
    first_exit_fraction=Decimal("0.67"),
    runner_target_r=Decimal("1.50"),
)
FROZEN_PARTIAL_RUNNER_FILTER = StrategyFilter(
    minimum_score=Decimal("0.45"),
    minimum_reward_risk=Decimal("1.20"),
    maximum_spread_pips=Decimal("0.6"),
    require_displacement=False,
    session_filter=SessionFilter.OPEN_ONLY,
    news_filter=NewsFilter.NONE,
    maximum_news_conflict=Decimal("0.10"),
    minimum_news_confidence=Decimal("0.20"),
    post_news_cooldown_minutes=10,
)
FROZEN_PARTIAL_RUNNER_GATE = ShadowRegimeGate(
    lookback=10,
    minimum_samples=6,
    minimum_economic_win_rate=Decimal("0.50"),
    minimum_expectancy_r=Decimal("0"),
)
FROZEN_PARTIAL_RUNNER_DIRECTION = Direction.SHORT
FROZEN_PARTIAL_RUNNER_DEVELOPMENT_PERIOD = "2026-05-20/2026-08-07"
FROZEN_PARTIAL_RUNNER_SOURCE_SHA = "ed8b7da024957430eebae3c1088446084b0cd6b6"


def frozen_policy_identity() -> str:
    return (
        f"{FROZEN_PARTIAL_RUNNER_PROFILE.identity}|"
        f"{FROZEN_PARTIAL_RUNNER_FILTER.identity}|"
        f"{FROZEN_PARTIAL_RUNNER_GATE.identity}|"
        f"instrument=ALL|direction={FROZEN_PARTIAL_RUNNER_DIRECTION.value}"
    )


def apply_frozen_partial_runner_policy(
    opportunities: Sequence[TickBacktestOpportunity],
    *,
    warmup_start: datetime,
    validation_start: datetime,
    validation_end: datetime,
) -> tuple[TickBacktestOpportunity, ...]:
    """Apply the development-frozen policy to a sealed window without reselection.

    Opportunities between ``warmup_start`` and ``validation_start`` are shadow-only.
    Their outcomes enter the causal regime state only after their real exit timestamps.
    Only decisions in the sealed validation interval are returned as capital trades.
    """
    boundaries = (warmup_start, validation_start, validation_end)
    if any(value.tzinfo is None for value in boundaries):
        raise ValueError("validation boundaries must be timezone-aware")
    if not warmup_start < validation_start < validation_end:
        raise ValueError("expected warmup_start < validation_start < validation_end")

    short_only = tuple(
        item for item in opportunities if item.trade.direction is FROZEN_PARTIAL_RUNNER_DIRECTION
    )
    base = filter_opportunities(
        short_only,
        FROZEN_PARTIAL_RUNNER_FILTER,
        start=warmup_start,
        end=validation_end,
    )
    warmed = apply_shadow_regime_gate(
        base,
        FROZEN_PARTIAL_RUNNER_GATE,
        evaluation_start=warmup_start,
        evaluation_end=validation_end,
    )
    return tuple(
        item for item in warmed if validation_start <= item.decision_time < validation_end
    )
