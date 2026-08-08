from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import uuid4

import pytest

import forex_trader.research.tick_backtest as module
from forex_trader.domain.enums import DecisionDisposition, Direction
from forex_trader.domain.macro_history import MacroObservation, PointInTimeFundamentalBook
from forex_trader.domain.models import TechnicalAssessment, TradeCandidate
from forex_trader.domain.sessions import SessionPhase
from forex_trader.research.backtest import BacktestTrade, OutcomeStatus
from forex_trader.research.public_history import HistoricalTick
from forex_trader.research.tick_backtest import (
    NewsFilter,
    SessionFilter,
    StrategyFilter,
    TickBacktestOpportunity,
    evaluate_candidate_on_ticks,
    evaluate_frozen_filter,
    filter_opportunities,
    generate_tick_opportunities,
    select_filters_on_calibration,
    simulate_daily_returns,
    strong_news_observation,
)

NOW = datetime(2026, 7, 14, 12, tzinfo=UTC)


def _candidate(direction: Direction, *, disposition: DecisionDisposition = DecisionDisposition.TRADE) -> TradeCandidate:
    long = direction is Direction.LONG
    return TradeCandidate(
        candidate_id=uuid4(),
        instrument="EUR_USD",
        direction=direction,
        disposition=disposition,
        score=Decimal("0.8"),
        entry_price=Decimal("1.1001") if long else Decimal("1.1000"),
        stop_loss=Decimal("1.0990") if long else Decimal("1.1011"),
        take_profit=Decimal("1.1020") if long else Decimal("1.0981"),
        technical_score=Decimal("0.8"),
        fundamental_score=Decimal("0"),
        reasons=(),
        signal_time=NOW,
    )


def _opportunity(
    index: int,
    *,
    score: str = "0.70",
    rr: str = "1.5",
    spread: str = "0.7",
    displacement: bool = True,
    phase: SessionPhase = SessionPhase.NEW_YORK_OPEN,
    news_directional: str = "0",
    news_confidence: str = "0",
    news_age: str | None = None,
    r: str = "1.3",
) -> TickBacktestOpportunity:
    decision = NOW + timedelta(minutes=30 * index)
    r_value = Decimal(r)
    status = OutcomeStatus.WIN if r_value > 0 else OutcomeStatus.LOSS
    trade = BacktestTrade("EUR_USD", Direction.LONG, decision, Decimal(score), status, r_value, 2)
    return TickBacktestOpportunity(
        "EUR_USD",
        decision,
        decision + timedelta(seconds=1),
        decision + timedelta(minutes=10),
        trade,
        Decimal(score),
        Decimal(rr),
        Decimal(spread),
        displacement,
        phase,
        Decimal(news_directional),
        Decimal(news_confidence),
        None if news_age is None else Decimal(news_age),
        "sweep_reclaim",
    )


def _strategy_filter(**overrides: object) -> StrategyFilter:
    values: dict[str, object] = {
        "minimum_score": Decimal("0.60"),
        "minimum_reward_risk": Decimal("1.20"),
        "maximum_spread_pips": Decimal("1.20"),
        "require_displacement": False,
        "session_filter": SessionFilter.ALL,
        "news_filter": NewsFilter.NONE,
    }
    values.update(overrides)
    return StrategyFilter(**values)  # type: ignore[arg-type]


def test_exact_short_target_stop_timeout_and_late_entry() -> None:
    short = _candidate(Direction.SHORT)
    win_ticks = (
        HistoricalTick("EUR_USD", NOW, Decimal("1.1000"), Decimal("1.1001")),
        HistoricalTick("EUR_USD", NOW + timedelta(seconds=2), Decimal("1.0980"), Decimal("1.0981")),
    )
    win = evaluate_candidate_on_ticks(short, win_ticks, entry_index=0, adverse_slippage_pips=Decimal("0"))
    assert win.trade.status is OutcomeStatus.WIN
    assert win.trade.r_multiple > 0

    stop_ticks = (
        win_ticks[0],
        HistoricalTick("EUR_USD", NOW + timedelta(seconds=2), Decimal("1.1011"), Decimal("1.1012")),
    )
    loss = evaluate_candidate_on_ticks(short, stop_ticks, entry_index=0, adverse_slippage_pips=Decimal("0"))
    assert loss.trade.status is OutcomeStatus.LOSS
    assert loss.trade.r_multiple <= Decimal("-1")

    timeout_ticks = (
        win_ticks[0],
        HistoricalTick("EUR_USD", NOW + timedelta(minutes=1), Decimal("1.0999"), Decimal("1.1000")),
    )
    timeout = evaluate_candidate_on_ticks(
        short,
        timeout_ticks,
        entry_index=0,
        maximum_holding=timedelta(minutes=1),
        adverse_slippage_pips=Decimal("0"),
    )
    assert timeout.trade.status is OutcomeStatus.TIMEOUT
    assert timeout.trade.exit_reason == "tick_time_stop"

    late = _candidate(Direction.LONG)
    far_tick = (HistoricalTick("EUR_USD", NOW, Decimal("1.1030"), Decimal("1.1031")),)
    invalid = evaluate_candidate_on_ticks(late, far_tick, entry_index=0, adverse_slippage_pips=Decimal("0"))
    assert invalid.trade.exit_reason == "late_entry_invalid_geometry"


def test_exact_tick_validation_errors() -> None:
    ticks = (HistoricalTick("EUR_USD", NOW, Decimal("1.1000"), Decimal("1.1001")),)
    with pytest.raises(ValueError, match="tradeable"):
        evaluate_candidate_on_ticks(
            _candidate(Direction.LONG, disposition=DecisionDisposition.ABSTAIN), ticks, entry_index=0
        )
    with pytest.raises(ValueError, match="outside"):
        evaluate_candidate_on_ticks(_candidate(Direction.LONG), ticks, entry_index=2)
    with pytest.raises(ValueError, match="positive"):
        evaluate_candidate_on_ticks(_candidate(Direction.LONG), ticks, entry_index=0, maximum_holding=timedelta(0))
    with pytest.raises(ValueError, match="cannot be negative"):
        evaluate_candidate_on_ticks(_candidate(Direction.LONG), ticks, entry_index=0, adverse_slippage_pips=Decimal("-1"))
    mismatched = (HistoricalTick("GBP_USD", NOW, Decimal("1.2"), Decimal("1.2001")),)
    with pytest.raises(ValueError, match="do not match"):
        evaluate_candidate_on_ticks(_candidate(Direction.LONG), mismatched, entry_index=0)


def test_strategy_filter_validation_and_identity() -> None:
    assert "score=0.60" in _strategy_filter().identity
    bad = [
        {"minimum_score": Decimal("1.1")},
        {"minimum_reward_risk": Decimal("1")},
        {"maximum_spread_pips": Decimal("0")},
        {"maximum_news_conflict": Decimal("-0.1")},
        {"minimum_news_confidence": Decimal("1.1")},
        {"post_news_cooldown_minutes": -1},
    ]
    for override in bad:
        with pytest.raises(ValueError):
            _strategy_filter(**override)


def test_filter_veto_branches() -> None:
    candidates = (
        _opportunity(0, score="0.55"),
        _opportunity(1, rr="1.1"),
        _opportunity(2, spread="1.5"),
        _opportunity(3, displacement=False),
        _opportunity(4, phase=SessionPhase.ASIA),
        _opportunity(5, news_directional="-0.4", news_confidence="0.8"),
        _opportunity(6, news_directional="0.2", news_confidence="0.8", news_age="2"),
        _opportunity(7, news_directional="0.2", news_confidence="0.8", news_age="30"),
    )
    strict = _strategy_filter(
        require_displacement=True,
        session_filter=SessionFilter.LIQUID,
        news_filter=NewsFilter.CONFLICT_VETO_COOLDOWN,
        post_news_cooldown_minutes=10,
    )
    assert filter_opportunities(candidates, strict) == (candidates[-1],)
    open_only = _strategy_filter(session_filter=SessionFilter.OPEN_ONLY)
    assert _opportunity(8, phase=SessionPhase.LONDON_CONTINUATION) not in filter_opportunities(
        (_opportunity(8, phase=SessionPhase.LONDON_CONTINUATION),), open_only
    )
    with pytest.raises(ValueError, match="timezone-aware"):
        filter_opportunities(candidates, strict, start=NOW.replace(tzinfo=None))
    with pytest.raises(ValueError, match="timezone-aware"):
        filter_opportunities(candidates, strict, end=NOW.replace(tzinfo=None))


def test_selection_and_return_validation_edges() -> None:
    with pytest.raises(ValueError, match="timezone-aware"):
        select_filters_on_calibration((), calibration_start=NOW.replace(tzinfo=None), calibration_end=NOW)
    with pytest.raises(ValueError, match="after"):
        select_filters_on_calibration((), calibration_start=NOW, calibration_end=NOW)
    with pytest.raises(ValueError, match="at least two"):
        select_filters_on_calibration((), calibration_start=NOW, calibration_end=NOW + timedelta(days=1), minimum_trades=1)
    losing = tuple(_opportunity(index, r="-1") for index in range(4))
    with pytest.raises(ValueError, match="positive-expectancy"):
        select_filters_on_calibration(
            losing,
            calibration_start=NOW,
            calibration_end=NOW + timedelta(days=1),
            filter_grid=(_strategy_filter(),),
            minimum_trades=2,
        )
    empty = simulate_daily_returns(())
    assert empty.trading_days == 0
    with pytest.raises(ValueError, match="risk_fraction"):
        simulate_daily_returns((), risk_fraction_per_trade=Decimal("0"))


def test_frozen_filter_and_strong_news_helper() -> None:
    wins = tuple(_opportunity(index, r="1.2") for index in range(8))
    strategy_filter = _strategy_filter()
    robust, _ = select_filters_on_calibration(
        wins,
        calibration_start=NOW,
        calibration_end=NOW + timedelta(hours=3),
        filter_grid=(strategy_filter,),
        minimum_trades=2,
    )
    frozen = evaluate_frozen_filter(
        wins,
        selection=robust,
        calibration_start=NOW,
        calibration_end=NOW + timedelta(hours=3),
        holdout_end=NOW + timedelta(hours=6),
        objective="test",
    )
    assert frozen.objective == "test"
    assert frozen.calibration_report.expectancy_r > 0
    strong = MacroObservation.news(
        currency="USD",
        headline="Federal Reserve rate hike as inflation accelerates",
        available_at=NOW,
    )
    weak = MacroObservation.news(currency="USD", headline="Local event", available_at=NOW)
    assert strong_news_observation(strong)
    assert not strong_news_observation(weak)


def test_generate_opportunities_uses_quote_after_signal_bar(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    start = datetime(2026, 7, 1, tzinfo=UTC)
    ticks = tuple(
        HistoricalTick(
            "EUR_USD",
            start + timedelta(minutes=5 * index),
            Decimal("1.1000") + Decimal(index % 4) * Decimal("0.00001"),
            Decimal("1.1001") + Decimal(index % 4) * Decimal("0.00001"),
        )
        for index in range(12 * 63)
    )

    def fake_assessment(instrument, lower, higher, **kwargs):  # type: ignore[no-untyped-def]
        signal_time = lower[-1].time + timedelta(minutes=5)
        return TechnicalAssessment(
            instrument=instrument,
            direction=Direction.LONG,
            score=Decimal("0.80"),
            atr=Decimal("0.0005"),
            rsi=Decimal("50"),
            entry_reference=Decimal("1.1001"),
            stop_reference=Decimal("1.0950"),
            take_profit_reference=Decimal("1.1100"),
            reasons=("synthetic research setup",),
            signal_time=signal_time,
            liquidity_sweep=True,
            displacement=True,
            reward_risk=Decimal("1.9"),
            setup_family="sweep_reclaim",
            setup_state="confirmed",
            structure_shift=True,
            retest_confirmed=True,
            location_score=Decimal("0.8"),
        )

    monkeypatch.setattr(module, "assess_technicals", fake_assessment)
    opportunities = generate_tick_opportunities(
        instrument="EUR_USD",
        ticks=ticks,
        fundamentals=PointInTimeFundamentalBook(),
        entry_latency=timedelta(0),
        maximum_decision_quote_age=timedelta(seconds=1),
        maximum_holding=timedelta(minutes=5),
        adverse_slippage_pips=Decimal("0"),
    )
    assert opportunities
    assert all(item.entry_time >= item.decision_time for item in opportunities)
