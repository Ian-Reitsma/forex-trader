from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from forex_trader.domain.enums import Direction
from forex_trader.domain.sessions import SessionPhase
from forex_trader.research.adaptive_managed_strategy import (
    AdaptiveManagedPolicy,
    AdaptivePolicyReport,
    ManagedCohortPolicy,
    ShadowRegimeGate,
    _cohort_source,
    _fold_boundaries,
    _lower_confidence_expectancy,
    apply_shadow_regime_gate,
    economic_win_rate,
    evaluate_frozen_adaptive_policy,
    select_stable_adaptive_policies,
)
from forex_trader.research.backtest import BacktestTrade, OutcomeStatus, summarize_trades
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


def _opportunity(
    index: int,
    r_value: str,
    *,
    instrument: str = "EUR_USD",
    direction: Direction = Direction.LONG,
) -> TickBacktestOpportunity:
    decision = NOW + timedelta(hours=index)
    realized = Decimal(r_value)
    trade = BacktestTrade(
        instrument=instrument,
        direction=direction,
        signal_time=decision,
        score=Decimal("0.70"),
        status=OutcomeStatus.WIN if realized > 0 else OutcomeStatus.LOSS,
        r_multiple=realized,
        bars_held=1,
    )
    return TickBacktestOpportunity(
        instrument=instrument,
        decision_time=decision,
        entry_time=decision + timedelta(seconds=1),
        exit_time=decision + timedelta(minutes=5),
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


def test_policy_value_objects_reject_invalid_contracts() -> None:
    with pytest.raises(ValueError, match="take_profit_r"):
        ManagedCohortPolicy(_filter(), Decimal("0"))
    with pytest.raises(ValueError, match="broker form"):
        ManagedCohortPolicy(_filter(), Decimal("0.5"), instrument="EURUSD")
    with pytest.raises(ValueError, match="cannot be flat"):
        ManagedCohortPolicy(_filter(), Decimal("0.5"), direction=Direction.FLAT)

    with pytest.raises(ValueError, match="lookback"):
        ShadowRegimeGate(2, 2, Decimal("0.5"), Decimal("0"))
    with pytest.raises(ValueError, match="minimum_samples"):
        ShadowRegimeGate(4, 5, Decimal("0.5"), Decimal("0"))
    with pytest.raises(ValueError, match="minimum_samples"):
        ShadowRegimeGate(4, 1, Decimal("0.5"), Decimal("0"))
    with pytest.raises(ValueError, match="economic_win_rate"):
        ShadowRegimeGate(4, 2, Decimal("1.01"), Decimal("0"))


def test_empty_metrics_and_fold_validation_are_fail_closed() -> None:
    assert economic_win_rate(()) == Decimal("0")
    assert _lower_confidence_expectancy(()) == Decimal("-999")
    assert _lower_confidence_expectancy((_opportunity(0, "0.5"),)) == Decimal("-999")
    with pytest.raises(ValueError, match="folds"):
        _fold_boundaries(NOW, NOW + timedelta(hours=1), folds=1)


def test_cohort_source_filters_instrument_and_direction() -> None:
    values = (
        _opportunity(0, "0.5", instrument="EUR_USD", direction=Direction.LONG),
        _opportunity(1, "0.5", instrument="EUR_USD", direction=Direction.SHORT),
        _opportunity(2, "0.5", instrument="GBP_USD", direction=Direction.LONG),
    )
    cohort = ManagedCohortPolicy(
        _filter(),
        Decimal("0.5"),
        instrument="EUR_USD",
        direction=Direction.LONG,
    )
    selected = _cohort_source(values, cohort, start=NOW, end=NOW + timedelta(hours=4))
    assert len(selected) == 1
    assert selected[0].instrument == "EUR_USD"
    assert selected[0].trade.direction is Direction.LONG
    assert "instrument=EUR_USD" in cohort.identity
    assert "direction=long" in cohort.identity


def test_shadow_gate_rejects_bad_evaluation_boundaries() -> None:
    gate = ShadowRegimeGate(4, 2, Decimal("0.5"), Decimal("0"))
    with pytest.raises(ValueError, match="timezone-aware"):
        apply_shadow_regime_gate(
            (),
            gate,
            evaluation_start=NOW.replace(tzinfo=None),
            evaluation_end=NOW + timedelta(hours=1),
        )
    with pytest.raises(ValueError, match="after"):
        apply_shadow_regime_gate((), gate, evaluation_start=NOW, evaluation_end=NOW)


def test_selector_rejects_invalid_ranges_and_unstable_history() -> None:
    with pytest.raises(ValueError, match="timezone-aware"):
        select_stable_adaptive_policies(
            {Decimal("0.5"): ()},
            development_start=NOW.replace(tzinfo=None),
            development_end=NOW + timedelta(hours=3),
            instruments=("EUR_USD",),
        )
    with pytest.raises(ValueError, match="after"):
        select_stable_adaptive_policies(
            {Decimal("0.5"): ()},
            development_start=NOW,
            development_end=NOW,
            instruments=("EUR_USD",),
        )
    with pytest.raises(ValueError, match="sample floors"):
        select_stable_adaptive_policies(
            {Decimal("0.5"): ()},
            development_start=NOW,
            development_end=NOW + timedelta(hours=3),
            instruments=("EUR_USD",),
            minimum_total_trades=5,
        )

    losses = tuple(_opportunity(index, "-1") for index in range(30))
    with pytest.raises(ValueError, match="no base cohort"):
        select_stable_adaptive_policies(
            {Decimal("0.5"): losses},
            development_start=NOW,
            development_end=NOW + timedelta(hours=30),
            instruments=("EUR_USD",),
            minimum_total_trades=12,
            minimum_fold_trades=2,
            entry_filters=(_filter(),),
            gates=(ShadowRegimeGate(4, 2, Decimal("0.5"), Decimal("0")),),
        )


def test_frozen_adaptive_policy_uses_shadow_warmup_before_evaluation() -> None:
    opportunities = tuple(
        _opportunity(index, "0.5" if index % 5 else "-0.2")
        for index in range(16)
    )
    gate = ShadowRegimeGate(4, 2, Decimal("0.5"), Decimal("0"))
    cohort = ManagedCohortPolicy(_filter(), Decimal("0.5"))
    policy = AdaptiveManagedPolicy(cohort, gate)
    development = apply_shadow_regime_gate(
        opportunities,
        gate,
        evaluation_start=NOW + timedelta(hours=4),
        evaluation_end=NOW + timedelta(hours=12),
    )
    report = AdaptivePolicyReport(
        policy=policy,
        report=summarize_trades([item.trade for item in development]),
        economic_wins=sum(item.trade.r_multiple > 0 for item in development),
        economic_win_rate=economic_win_rate(development),
        lower_confidence_expectancy_r=_lower_confidence_expectancy(development),
        fold_expectancies=(Decimal("0.1"), Decimal("0.1"), Decimal("0.1")),
        fold_economic_win_rates=(Decimal("0.7"), Decimal("0.7"), Decimal("0.7")),
        fold_trade_counts=(2, 2, 2),
    )
    selected, frozen_report, frozen_win_rate = evaluate_frozen_adaptive_policy(
        {Decimal("0.5"): opportunities},
        policy_report=report,
        history_start=NOW,
        evaluation_start=NOW + timedelta(hours=8),
        evaluation_end=NOW + timedelta(hours=16),
    )
    assert selected
    assert all(item.decision_time >= NOW + timedelta(hours=8) for item in selected)
    assert frozen_report.trades == len(selected)
    assert frozen_win_rate == economic_win_rate(selected)
