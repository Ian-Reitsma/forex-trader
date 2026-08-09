from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import uuid4

from forex_trader.domain.enums import DecisionDisposition, Direction
from forex_trader.domain.models import TradeCandidate
from forex_trader.domain.sessions import SessionPhase
from forex_trader.research.backtest import BacktestTrade, OutcomeStatus
from forex_trader.research.managed_tick_backtest import (
    evaluate_candidate_on_ticks_for_targets,
    select_managed_profiles_on_calibration,
)
from forex_trader.research.public_history import HistoricalTick
from forex_trader.research.tick_backtest import (
    NewsFilter,
    SessionFilter,
    StrategyFilter,
    TickBacktestOpportunity,
)

NOW = datetime(2026, 7, 14, 12, tzinfo=UTC)


def _candidate() -> TradeCandidate:
    return TradeCandidate(
        candidate_id=uuid4(),
        instrument="EUR_USD",
        direction=Direction.LONG,
        disposition=DecisionDisposition.TRADE,
        score=Decimal("0.75"),
        entry_price=Decimal("1.1001"),
        stop_loss=Decimal("1.0991"),
        take_profit=Decimal("1.1020"),
        technical_score=Decimal("0.75"),
        fundamental_score=Decimal("0"),
        reasons=(),
        signal_time=NOW,
    )


def test_multi_target_path_can_bank_small_target_before_later_stop() -> None:
    ticks = (
        HistoricalTick("EUR_USD", NOW, Decimal("1.1000"), Decimal("1.1001")),
        HistoricalTick("EUR_USD", NOW + timedelta(seconds=5), Decimal("1.1007"), Decimal("1.1008")),
        HistoricalTick("EUR_USD", NOW + timedelta(seconds=10), Decimal("1.0990"), Decimal("1.0991")),
    )
    outcomes = evaluate_candidate_on_ticks_for_targets(
        _candidate(),
        ticks,
        entry_index=0,
        take_profit_targets_r=(Decimal("0.50"), Decimal("0.80")),
        adverse_slippage_pips=Decimal("0"),
    )
    assert outcomes[Decimal("0.50")].trade.status is OutcomeStatus.WIN
    assert outcomes[Decimal("0.80")].trade.status is OutcomeStatus.LOSS
    assert outcomes[Decimal("0.50")].exit_time == ticks[1].time
    assert outcomes[Decimal("0.80")].exit_time == ticks[2].time


def _opportunity(index: int, *, r_multiple: str) -> TickBacktestOpportunity:
    decision = NOW + timedelta(minutes=15 * index)
    r_value = Decimal(r_multiple)
    status = OutcomeStatus.WIN if r_value > 0 else OutcomeStatus.LOSS
    trade = BacktestTrade(
        "EUR_USD",
        Direction.LONG,
        decision,
        Decimal("0.72"),
        status,
        r_value,
        1,
    )
    return TickBacktestOpportunity(
        instrument="EUR_USD",
        decision_time=decision,
        entry_time=decision + timedelta(seconds=1),
        exit_time=decision + timedelta(minutes=5),
        trade=trade,
        technical_score=Decimal("0.72"),
        reward_risk=Decimal("1.5"),
        spread_pips=Decimal("0.6"),
        displacement=True,
        session_phase=SessionPhase.NEW_YORK_OPEN,
        news_directional=Decimal("0"),
        news_confidence=Decimal("0"),
        latest_news_age_minutes=None,
        setup_family="sweep_reclaim",
    )


def test_managed_selection_can_choose_high_win_positive_expectancy_target() -> None:
    low_target = tuple(_opportunity(i, r_multiple="0.48" if i < 8 else "-1.02") for i in range(10))
    high_target = tuple(_opportunity(i, r_multiple="0.78" if i < 5 else "-1.02") for i in range(10))
    strategy_filter = StrategyFilter(
        Decimal("0.60"),
        Decimal("1.2"),
        Decimal("1.0"),
        True,
        SessionFilter.ALL,
        NewsFilter.NONE,
    )
    robust, win_target = select_managed_profiles_on_calibration(
        {
            Decimal("0.50"): low_target,
            Decimal("0.80"): high_target,
        },
        calibration_start=NOW,
        calibration_end=NOW + timedelta(hours=4),
        filter_grid=(strategy_filter,),
        minimum_trades=10,
    )
    assert robust.take_profit_r == Decimal("0.50")
    assert win_target.take_profit_r == Decimal("0.50")
    assert win_target.selection.report.win_rate == Decimal("0.8")
    assert win_target.selection.report.expectancy_r > 0
