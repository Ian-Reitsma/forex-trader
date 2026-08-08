from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

from forex_trader.domain.enums import Direction
from forex_trader.domain.sessions import SessionPhase
from forex_trader.research.backtest import BacktestTrade, OutcomeStatus
from forex_trader.research.scalp_target import (
    ScalpTargetPolicy,
    apply_scalp_target,
    summarize_scalp_target,
)
from forex_trader.research.tick_backtest import (
    NewsFilter,
    SessionFilter,
    StrategyFilter,
    TickBacktestOpportunity,
)


def _filter() -> StrategyFilter:
    return StrategyFilter(
        minimum_score=Decimal("0.50"),
        minimum_reward_risk=Decimal("1.01"),
        maximum_spread_pips=Decimal("2"),
        require_displacement=False,
        session_filter=SessionFilter.ALL,
        news_filter=NewsFilter.NONE,
    )


def _opportunity(
    *,
    status: OutcomeStatus,
    realized_r: Decimal,
    mfe_r: Decimal,
    mae_r: Decimal = Decimal("1"),
) -> TickBacktestOpportunity:
    decision = datetime(2026, 7, 1, 13, tzinfo=UTC)
    trade = BacktestTrade(
        instrument="EUR_USD",
        direction=Direction.LONG,
        signal_time=decision,
        score=Decimal("0.70"),
        status=status,
        r_multiple=realized_r,
        bars_held=4,
        exit_reason="original",
        maximum_favorable_r=mfe_r,
        maximum_adverse_r=mae_r,
        estimated_cost_r=Decimal("0.04"),
    )
    return TickBacktestOpportunity(
        instrument="EUR_USD",
        decision_time=decision,
        entry_time=decision + timedelta(seconds=1),
        exit_time=decision + timedelta(minutes=20),
        trade=trade,
        technical_score=Decimal("0.70"),
        reward_risk=Decimal("2"),
        spread_pips=Decimal("0.7"),
        displacement=True,
        session_phase=SessionPhase.LONDON_NEW_YORK_OVERLAP,
        news_directional=Decimal("0"),
        news_confidence=Decimal("0"),
        latest_news_age_minutes=None,
        setup_family="zone_liquidity_sweep_reclaim",
    )


def test_smaller_target_converts_prior_stop_when_exact_mfe_proves_target_was_first() -> None:
    original = _opportunity(
        status=OutcomeStatus.LOSS,
        realized_r=Decimal("-1.02"),
        mfe_r=Decimal("0.50"),
    )
    policy = ScalpTargetPolicy(_filter(), Decimal("0.33"))
    selected = apply_scalp_target((original,), policy)
    assert len(selected) == 1
    assert selected[0].trade.status is OutcomeStatus.WIN
    assert selected[0].trade.r_multiple == Decimal("0.31")
    assert selected[0].trade.exit_reason == "scalp_target_0.33"


def test_unreached_scalp_target_preserves_original_loss() -> None:
    original = _opportunity(
        status=OutcomeStatus.LOSS,
        realized_r=Decimal("-1.02"),
        mfe_r=Decimal("0.20"),
    )
    policy = ScalpTargetPolicy(_filter(), Decimal("0.33"))
    selected = apply_scalp_target((original,), policy)
    assert selected[0].trade == original.trade


def test_economic_win_rate_counts_profitable_time_stop_separately_from_target_hit_rate() -> None:
    original = _opportunity(
        status=OutcomeStatus.TIMEOUT,
        realized_r=Decimal("0.10"),
        mfe_r=Decimal("0.20"),
        mae_r=Decimal("0.15"),
    )
    policy = ScalpTargetPolicy(_filter(), Decimal("0.33"))
    selected = apply_scalp_target((original,), policy)
    report = summarize_scalp_target(selected, policy)
    assert report.report.win_rate == Decimal("0")
    assert report.economic_wins == 1
    assert report.economic_win_rate == Decimal("1")
