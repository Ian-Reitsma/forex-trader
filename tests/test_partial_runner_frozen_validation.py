from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

from forex_trader.domain.enums import Direction
from forex_trader.domain.sessions import SessionPhase
from forex_trader.research.backtest import BacktestTrade, OutcomeStatus
from forex_trader.research.partial_runner_frozen_validation import (
    FROZEN_PARTIAL_RUNNER_DIRECTION,
    FROZEN_PARTIAL_RUNNER_FILTER,
    FROZEN_PARTIAL_RUNNER_GATE,
    FROZEN_PARTIAL_RUNNER_PROFILE,
    apply_frozen_partial_runner_policy,
)
from forex_trader.research.tick_backtest import NewsFilter, SessionFilter, TickBacktestOpportunity

NOW = datetime(2026, 4, 1, tzinfo=UTC)


def _opportunity(index: int, r_value: str, *, direction: Direction = Direction.SHORT) -> TickBacktestOpportunity:
    decision = NOW + timedelta(hours=index)
    realized = Decimal(r_value)
    status = OutcomeStatus.WIN if realized > 0 else OutcomeStatus.LOSS
    return TickBacktestOpportunity(
        instrument="EUR_USD",
        decision_time=decision,
        entry_time=decision + timedelta(seconds=1),
        exit_time=decision + timedelta(minutes=5),
        trade=BacktestTrade(
            instrument="EUR_USD",
            direction=direction,
            signal_time=decision,
            score=Decimal("0.70"),
            status=status,
            r_multiple=realized,
            bars_held=1,
        ),
        technical_score=Decimal("0.70"),
        reward_risk=Decimal("1.50"),
        spread_pips=Decimal("0.50"),
        displacement=False,
        session_phase=SessionPhase.LONDON_OPEN,
        news_directional=Decimal("0"),
        news_confidence=Decimal("0"),
        latest_news_age_minutes=None,
        setup_family="sweep_reclaim",
    )


def test_frozen_policy_matches_development_artifact() -> None:
    assert FROZEN_PARTIAL_RUNNER_PROFILE.first_target_r == Decimal("0.50")
    assert FROZEN_PARTIAL_RUNNER_PROFILE.first_exit_fraction == Decimal("0.67")
    assert FROZEN_PARTIAL_RUNNER_PROFILE.runner_target_r == Decimal("1.50")
    assert FROZEN_PARTIAL_RUNNER_FILTER.minimum_score == Decimal("0.45")
    assert FROZEN_PARTIAL_RUNNER_FILTER.minimum_reward_risk == Decimal("1.20")
    assert FROZEN_PARTIAL_RUNNER_FILTER.maximum_spread_pips == Decimal("0.6")
    assert FROZEN_PARTIAL_RUNNER_FILTER.session_filter is SessionFilter.OPEN_ONLY
    assert FROZEN_PARTIAL_RUNNER_FILTER.news_filter is NewsFilter.NONE
    assert FROZEN_PARTIAL_RUNNER_DIRECTION is Direction.SHORT
    assert FROZEN_PARTIAL_RUNNER_GATE.lookback == 10
    assert FROZEN_PARTIAL_RUNNER_GATE.minimum_samples == 6
    assert FROZEN_PARTIAL_RUNNER_GATE.minimum_economic_win_rate == Decimal("0.50")
    assert FROZEN_PARTIAL_RUNNER_GATE.minimum_expectancy_r == Decimal("0")


def test_warmup_outcomes_seed_gate_but_are_not_returned_as_validation_trades() -> None:
    opportunities = tuple(_opportunity(index, "0.50") for index in range(8))
    selected = apply_frozen_partial_runner_policy(
        opportunities,
        warmup_start=NOW,
        validation_start=NOW + timedelta(hours=7),
        validation_end=NOW + timedelta(hours=9),
    )
    assert tuple(item.decision_time for item in selected) == (NOW + timedelta(hours=7),)


def test_frozen_policy_rejects_long_candidates() -> None:
    opportunities = tuple(_opportunity(index, "0.50", direction=Direction.LONG) for index in range(8))
    selected = apply_frozen_partial_runner_policy(
        opportunities,
        warmup_start=NOW,
        validation_start=NOW + timedelta(hours=7),
        validation_end=NOW + timedelta(hours=9),
    )
    assert selected == ()
