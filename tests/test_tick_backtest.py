from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import uuid4

from forex_trader.domain.enums import DecisionDisposition, Direction
from forex_trader.domain.models import TradeCandidate
from forex_trader.domain.sessions import SessionPhase
from forex_trader.research.backtest import BacktestTrade, OutcomeStatus
from forex_trader.research.public_history import HistoricalTick
from forex_trader.research.tick_backtest import (
    NewsFilter,
    SessionFilter,
    StrategyFilter,
    TickBacktestOpportunity,
    evaluate_candidate_on_ticks,
    filter_opportunities,
    select_filters_on_calibration,
    simulate_daily_returns,
)

NOW = datetime(2026, 7, 14, 12, 0, tzinfo=UTC)


def _candidate(direction: Direction = Direction.LONG) -> TradeCandidate:
    return TradeCandidate(
        candidate_id=uuid4(),
        instrument="EUR_USD",
        direction=direction,
        disposition=DecisionDisposition.TRADE,
        score=Decimal("0.75"),
        entry_price=Decimal("1.1001") if direction is Direction.LONG else Decimal("1.1000"),
        stop_loss=Decimal("1.0990") if direction is Direction.LONG else Decimal("1.1011"),
        take_profit=Decimal("1.1020") if direction is Direction.LONG else Decimal("1.0981"),
        technical_score=Decimal("0.75"),
        fundamental_score=Decimal("0"),
        reasons=(),
        signal_time=NOW,
    )


def test_exact_tick_path_resolves_target_without_candle_ambiguity() -> None:
    ticks = (
        HistoricalTick("EUR_USD", NOW, Decimal("1.1000"), Decimal("1.1001")),
        HistoricalTick("EUR_USD", NOW + timedelta(seconds=5), Decimal("1.1008"), Decimal("1.1009")),
        HistoricalTick("EUR_USD", NOW + timedelta(seconds=9), Decimal("1.1021"), Decimal("1.1022")),
    )
    outcome = evaluate_candidate_on_ticks(_candidate(), ticks, entry_index=0, adverse_slippage_pips=Decimal("0"))
    assert outcome.trade.status is OutcomeStatus.WIN
    assert outcome.trade.exit_reason == "tick_target"
    assert outcome.exit_time == ticks[-1].time
    assert not outcome.trade.ambiguous_bar


def test_exact_tick_path_honors_stop_before_later_target() -> None:
    ticks = (
        HistoricalTick("EUR_USD", NOW, Decimal("1.1000"), Decimal("1.1001")),
        HistoricalTick("EUR_USD", NOW + timedelta(seconds=5), Decimal("1.0989"), Decimal("1.0990")),
        HistoricalTick("EUR_USD", NOW + timedelta(seconds=10), Decimal("1.1022"), Decimal("1.1023")),
    )
    outcome = evaluate_candidate_on_ticks(_candidate(), ticks, entry_index=0, adverse_slippage_pips=Decimal("0"))
    assert outcome.trade.status is OutcomeStatus.LOSS
    assert outcome.exit_time == ticks[1].time
    assert outcome.trade.r_multiple <= Decimal("-1")


def _opportunity(
    index: int,
    *,
    score: str = "0.70",
    reward_risk: str = "1.5",
    r_multiple: str = "1.5",
    spread: str = "0.7",
    displacement: bool = True,
    news_directional: str = "0",
    news_confidence: str = "0",
    news_age: str | None = None,
    duration_minutes: int = 20,
) -> TickBacktestOpportunity:
    decision = NOW + timedelta(minutes=30 * index)
    r_value = Decimal(r_multiple)
    status = OutcomeStatus.WIN if r_value > 0 else OutcomeStatus.LOSS
    trade = BacktestTrade(
        "EUR_USD",
        Direction.LONG,
        decision,
        Decimal(score),
        status,
        r_value,
        2,
    )
    return TickBacktestOpportunity(
        instrument="EUR_USD",
        decision_time=decision,
        entry_time=decision + timedelta(seconds=1),
        exit_time=decision + timedelta(minutes=duration_minutes),
        trade=trade,
        technical_score=Decimal(score),
        reward_risk=Decimal(reward_risk),
        spread_pips=Decimal(spread),
        displacement=displacement,
        session_phase=SessionPhase.NEW_YORK_OPEN,
        news_directional=Decimal(news_directional),
        news_confidence=Decimal(news_confidence),
        latest_news_age_minutes=None if news_age is None else Decimal(news_age),
        setup_family="sweep_reclaim",
    )


def test_filter_applies_news_conflict_and_post_news_cooldown() -> None:
    conflict = _opportunity(0, news_directional="-0.3", news_confidence="0.7", news_age="30")
    recent = _opportunity(1, news_directional="0.1", news_confidence="0.7", news_age="3")
    clean = _opportunity(2, news_directional="0.1", news_confidence="0.7", news_age="30")
    strategy_filter = StrategyFilter(
        Decimal("0.60"),
        Decimal("1.2"),
        Decimal("1.2"),
        True,
        SessionFilter.LIQUID,
        NewsFilter.CONFLICT_VETO_COOLDOWN,
        post_news_cooldown_minutes=10,
    )
    selected = filter_opportunities((conflict, recent, clean), strategy_filter)
    assert selected == (clean,)


def test_filter_enforces_one_open_trade_per_instrument() -> None:
    first = _opportunity(0, duration_minutes=50)
    overlapping = _opportunity(1, duration_minutes=10)
    later = _opportunity(2, duration_minutes=10)
    strategy_filter = StrategyFilter(
        Decimal("0.60"),
        Decimal("1.2"),
        Decimal("1.2"),
        False,
        SessionFilter.ALL,
        NewsFilter.NONE,
    )
    selected = filter_opportunities((first, overlapping, later), strategy_filter)
    assert selected == (first, later)


def test_calibration_selection_prefers_positive_repeatable_configuration() -> None:
    opportunities = []
    for index in range(12):
        opportunities.append(
            _opportunity(
                index,
                score="0.72" if index >= 4 else "0.55",
                r_multiple="1.4" if index >= 4 else "-1",
                duration_minutes=5,
            )
        )
    broad = StrategyFilter(
        Decimal("0.50"), Decimal("1.2"), Decimal("1.2"), False, SessionFilter.ALL, NewsFilter.NONE
    )
    selective = StrategyFilter(
        Decimal("0.70"), Decimal("1.2"), Decimal("1.2"), False, SessionFilter.ALL, NewsFilter.NONE
    )
    robust, win_target = select_filters_on_calibration(
        opportunities,
        calibration_start=NOW,
        calibration_end=NOW + timedelta(hours=7),
        filter_grid=(broad, selective),
        minimum_trades=4,
    )
    assert robust.strategy_filter == selective
    assert win_target.strategy_filter == selective
    assert robust.report.win_rate == Decimal("1")


def test_daily_return_simulation_compounds_realized_r() -> None:
    first = _opportunity(0, r_multiple="1", duration_minutes=5)
    second = _opportunity(1, r_multiple="2", duration_minutes=5)
    report = simulate_daily_returns((first, second), risk_fraction_per_trade=Decimal("0.01"))
    assert report.trading_days == 1
    assert report.total_return == Decimal("0.0302")
    assert report.average_daily_return == Decimal("0.0302")
    assert report.profitable_day_fraction == Decimal("1")
