from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

from forex_trader.domain.enums import Direction
from forex_trader.domain.sessions import SessionPhase
from forex_trader.research.adaptive_managed_strategy import (
    ManagedCohortPolicy,
    ShadowRegimeGate,
    apply_shadow_regime_gate,
    economic_win_rate,
    select_stable_adaptive_policies,
)
from forex_trader.research.backtest import BacktestTrade, OutcomeStatus
from forex_trader.research.tick_backtest import (
    NewsFilter,
    SessionFilter,
    StrategyFilter,
    TickBacktestOpportunity,
)

NOW = datetime(2026, 7, 1, tzinfo=UTC)


def _filter() -> StrategyFilter:
    return StrategyFilter(
        minimum_score=Decimal("0.50"),
        minimum_reward_risk=Decimal("1.05"),
        maximum_spread_pips=Decimal("1.2"),
        require_displacement=False,
        session_filter=SessionFilter.LIQUID,
        news_filter=NewsFilter.NONE,
    )


def _opportunity(index: int, r_value: str, *, duration_minutes: int = 5) -> TickBacktestOpportunity:
    decision = NOW + timedelta(hours=index)
    realized = Decimal(r_value)
    status = OutcomeStatus.WIN if realized > 0 else OutcomeStatus.LOSS
    trade = BacktestTrade(
        instrument="EUR_USD",
        direction=Direction.LONG,
        signal_time=decision,
        score=Decimal("0.70"),
        status=status,
        r_multiple=realized,
        bars_held=1,
    )
    return TickBacktestOpportunity(
        instrument="EUR_USD",
        decision_time=decision,
        entry_time=decision + timedelta(seconds=1),
        exit_time=decision + timedelta(minutes=duration_minutes),
        trade=trade,
        technical_score=Decimal("0.70"),
        reward_risk=Decimal("1.5"),
        spread_pips=Decimal("0.5"),
        displacement=True,
        session_phase=SessionPhase.LONDON_NEW_YORK_OVERLAP,
        news_directional=Decimal("0"),
        news_confidence=Decimal("0"),
        latest_news_age_minutes=None,
        setup_family="sweep_reclaim",
    )


def test_shadow_gate_uses_only_completed_prior_outcomes_and_recovers() -> None:
    # First four shadow trades establish a strong regime. The next three losses
    # degrade the rolling window and gate capital off; later shadow wins restore it.
    values = ("0.5", "0.5", "0.5", "0.5", "-1", "-1", "-1", "0.5", "0.5", "0.5", "0.5")
    opportunities = tuple(_opportunity(i, value) for i, value in enumerate(values))
    gate = ShadowRegimeGate(
        lookback=4,
        minimum_samples=4,
        minimum_economic_win_rate=Decimal("0.75"),
        minimum_expectancy_r=Decimal("0"),
    )
    selected = apply_shadow_regime_gate(
        opportunities,
        gate,
        evaluation_start=NOW,
        evaluation_end=NOW + timedelta(hours=20),
    )
    selected_indices = tuple(int((item.decision_time - NOW).total_seconds() // 3600) for item in selected)
    assert 4 in selected_indices
    assert 7 not in selected_indices
    assert 10 in selected_indices


def test_shadow_gate_does_not_use_outcome_before_exit() -> None:
    first = _opportunity(0, "0.5", duration_minutes=180)
    second = _opportunity(1, "0.5")
    third = _opportunity(2, "0.5")
    gate = ShadowRegimeGate(lookback=3, minimum_samples=2, minimum_economic_win_rate=Decimal("0.5"), minimum_expectancy_r=Decimal("0"))
    selected = apply_shadow_regime_gate(
        (first, second, third),
        gate,
        evaluation_start=NOW,
        evaluation_end=NOW + timedelta(hours=5),
    )
    # At the third decision only the second setup has completed; the long-running
    # first trade's future win is not available, so minimum_samples is not met.
    assert selected == ()


def test_stable_selector_requires_multi_fold_edge() -> None:
    opportunities = tuple(_opportunity(i, "0.50" if i % 4 else "-0.20") for i in range(36))
    strategy_filter = _filter()
    gate = ShadowRegimeGate(6, 4, Decimal("0.50"), Decimal("0"))
    robust, win_target = select_stable_adaptive_policies(
        {Decimal("0.50"): opportunities},
        development_start=NOW,
        development_end=NOW + timedelta(hours=36),
        instruments=("EUR_USD",),
        minimum_total_trades=12,
        minimum_fold_trades=2,
        entry_filters=(strategy_filter,),
        gates=(gate,),
        top_base_candidates=4,
    )
    assert robust.policy.cohort == ManagedCohortPolicy(strategy_filter, Decimal("0.50"))
    assert robust.report.expectancy_r > 0
    assert economic_win_rate(opportunities) > Decimal("0.70")
    assert win_target.economic_win_rate >= Decimal("0.70")
