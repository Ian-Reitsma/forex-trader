from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import uuid4

import pytest

from forex_trader.domain.enums import DecisionDisposition, Direction
from forex_trader.domain.macro_history import PointInTimeFundamentalBook
from forex_trader.domain.models import TradeCandidate
from forex_trader.domain.sessions import SessionPhase
from forex_trader.research.backtest import BacktestTrade, OutcomeStatus
from forex_trader.research.managed_tick_backtest import (
    _validate_targets,
    evaluate_candidate_on_ticks_for_targets,
    evaluate_managed_selection,
    generate_profit_target_opportunities,
    select_managed_profiles_on_calibration,
)
from forex_trader.research.public_history import HistoricalTick
from forex_trader.research.tick_backtest import (
    NewsFilter,
    SessionFilter,
    StrategyFilter,
    TickBacktestOpportunity,
)

NOW = datetime(2026, 7, 15, 12, tzinfo=UTC)


def _candidate(*, direction: Direction = Direction.LONG) -> TradeCandidate:
    if direction is Direction.LONG:
        entry, stop, target = Decimal("1.1001"), Decimal("1.0991"), Decimal("1.1021")
    else:
        entry, stop, target = Decimal("1.1000"), Decimal("1.1010"), Decimal("1.0980")
    return TradeCandidate(
        candidate_id=uuid4(),
        instrument="EUR_USD",
        direction=direction,
        disposition=DecisionDisposition.TRADE,
        score=Decimal("0.75"),
        entry_price=entry,
        stop_loss=stop,
        take_profit=target,
        technical_score=Decimal("0.75"),
        fundamental_score=Decimal("0"),
        reasons=(),
        signal_time=NOW,
    )


def _opportunity(index: int, r_multiple: Decimal) -> TickBacktestOpportunity:
    instant = NOW + timedelta(minutes=15 * index)
    trade = BacktestTrade(
        "EUR_USD",
        Direction.LONG,
        instant,
        Decimal("0.72"),
        OutcomeStatus.WIN if r_multiple > 0 else OutcomeStatus.LOSS,
        r_multiple,
        1,
    )
    return TickBacktestOpportunity(
        instrument="EUR_USD",
        decision_time=instant,
        entry_time=instant + timedelta(seconds=1),
        exit_time=instant + timedelta(minutes=5),
        trade=trade,
        technical_score=Decimal("0.72"),
        reward_risk=Decimal("1.5"),
        spread_pips=Decimal("0.5"),
        displacement=True,
        session_phase=SessionPhase.NEW_YORK_OPEN,
        news_directional=Decimal("0"),
        news_confidence=Decimal("0"),
        latest_news_age_minutes=None,
        setup_family="sweep_reclaim",
    )


def _filter() -> StrategyFilter:
    return StrategyFilter(
        Decimal("0.60"),
        Decimal("1.2"),
        Decimal("1.0"),
        True,
        SessionFilter.ALL,
        NewsFilter.NONE,
    )


def test_target_validation_rejects_empty_and_out_of_range_values() -> None:
    with pytest.raises(ValueError, match="at least one"):
        _validate_targets(())
    with pytest.raises(ValueError, match="in \(0,1\]"):
        _validate_targets((Decimal("0"),))
    with pytest.raises(ValueError, match="in \(0,1\]"):
        _validate_targets((Decimal("1.01"),))
    assert _validate_targets((Decimal("0.5"), Decimal("0.35"), Decimal("0.5"))) == (
        Decimal("0.35"),
        Decimal("0.5"),
    )


def test_managed_tick_evaluator_rejects_invalid_inputs() -> None:
    ticks = (HistoricalTick("EUR_USD", NOW, Decimal("1.1000"), Decimal("1.1001")),)
    abstain = replace(_candidate(), disposition=DecisionDisposition.ABSTAIN)
    with pytest.raises(ValueError, match="tradeable"):
        evaluate_candidate_on_ticks_for_targets(abstain, ticks, entry_index=0)
    with pytest.raises(ValueError, match="entry, stop, and target"):
        evaluate_candidate_on_ticks_for_targets(replace(_candidate(), entry_price=None), ticks, entry_index=0)
    with pytest.raises(ValueError, match="outside tick history"):
        evaluate_candidate_on_ticks_for_targets(_candidate(), ticks, entry_index=1)
    with pytest.raises(ValueError, match="maximum_holding"):
        evaluate_candidate_on_ticks_for_targets(_candidate(), ticks, entry_index=0, maximum_holding=timedelta(0))
    with pytest.raises(ValueError, match="slippage"):
        evaluate_candidate_on_ticks_for_targets(
            _candidate(), ticks, entry_index=0, adverse_slippage_pips=Decimal("-0.1")
        )
    wrong = (HistoricalTick("GBP_USD", NOW, Decimal("1.1000"), Decimal("1.1001")),)
    with pytest.raises(ValueError, match="do not match"):
        evaluate_candidate_on_ticks_for_targets(_candidate(), wrong, entry_index=0)
    with pytest.raises(ValueError, match="flat"):
        evaluate_candidate_on_ticks_for_targets(replace(_candidate(), direction=Direction.FLAT), ticks, entry_index=0)


def test_short_target_and_timeout_paths_use_executable_ask() -> None:
    ticks = (
        HistoricalTick("EUR_USD", NOW, Decimal("1.1000"), Decimal("1.1001")),
        HistoricalTick("EUR_USD", NOW + timedelta(seconds=5), Decimal("1.0993"), Decimal("1.0994")),
        HistoricalTick("EUR_USD", NOW + timedelta(seconds=10), Decimal("1.1010"), Decimal("1.1011")),
    )
    outcomes = evaluate_candidate_on_ticks_for_targets(
        _candidate(direction=Direction.SHORT),
        ticks,
        entry_index=0,
        take_profit_targets_r=(Decimal("0.50"), Decimal("0.80")),
        adverse_slippage_pips=Decimal("0"),
    )
    assert outcomes[Decimal("0.50")].trade.status is OutcomeStatus.WIN
    assert outcomes[Decimal("0.80")].trade.status is OutcomeStatus.LOSS

    timeout_ticks = (
        ticks[0],
        HistoricalTick("EUR_USD", NOW + timedelta(minutes=1), Decimal("1.1001"), Decimal("1.1002")),
    )
    timeout = evaluate_candidate_on_ticks_for_targets(
        _candidate(direction=Direction.SHORT),
        timeout_ticks,
        entry_index=0,
        take_profit_targets_r=(Decimal("0.50"),),
        maximum_holding=timedelta(minutes=1),
        adverse_slippage_pips=Decimal("0"),
    )[Decimal("0.50")]
    assert timeout.trade.status is OutcomeStatus.TIMEOUT
    assert timeout.exit_time == timeout_ticks[-1].time


def test_generator_returns_empty_profiles_when_history_is_too_short() -> None:
    book = PointInTimeFundamentalBook(())
    empty = generate_profit_target_opportunities(
        instrument="EUR_USD",
        ticks=(),
        fundamentals=book,
        take_profit_targets_r=(Decimal("0.35"), Decimal("0.50")),
    )
    assert empty == {Decimal("0.35"): (), Decimal("0.50"): ()}

    ticks = (
        HistoricalTick("EUR_USD", NOW, Decimal("1.1000"), Decimal("1.1001")),
        HistoricalTick("EUR_USD", NOW + timedelta(seconds=1), Decimal("1.1001"), Decimal("1.1002")),
    )
    short = generate_profit_target_opportunities(
        instrument="EUR_USD",
        ticks=ticks,
        fundamentals=book,
        take_profit_targets_r=(Decimal("0.35"),),
    )
    assert short == {Decimal("0.35"): ()}


def test_managed_selection_rejects_all_negative_profiles() -> None:
    losses = tuple(_opportunity(index, Decimal("-1")) for index in range(10))
    with pytest.raises(ValueError, match="no managed target"):
        select_managed_profiles_on_calibration(
            {Decimal("0.50"): losses},
            calibration_start=NOW,
            calibration_end=NOW + timedelta(hours=4),
            filter_grid=(_filter(),),
            minimum_trades=10,
        )


def test_managed_selection_can_be_frozen_and_evaluated() -> None:
    calibration = tuple(
        _opportunity(index, Decimal("0.5") if index < 8 else Decimal("-1"))
        for index in range(10)
    )
    later = tuple(
        replace(
            _opportunity(20 + index, Decimal("0.5") if index < 3 else Decimal("-1")),
            decision_time=NOW + timedelta(hours=5, minutes=15 * index),
            entry_time=NOW + timedelta(hours=5, minutes=15 * index, seconds=1),
            exit_time=NOW + timedelta(hours=5, minutes=15 * index + 5),
        )
        for index in range(4)
    )
    opportunities = calibration + later
    robust, _ = select_managed_profiles_on_calibration(
        {Decimal("0.50"): opportunities},
        calibration_start=NOW,
        calibration_end=NOW + timedelta(hours=4),
        filter_grid=(_filter(),),
        minimum_trades=10,
    )
    frozen = evaluate_managed_selection(
        {Decimal("0.50"): opportunities},
        managed_selection=robust,
        calibration_start=NOW,
        calibration_end=NOW + timedelta(hours=4),
        holdout_end=NOW + timedelta(hours=8),
        objective="edge-test",
    )
    assert frozen.take_profit_r == Decimal("0.50")
    assert frozen.frozen.objective == "edge-test"
    assert frozen.frozen.holdout_report.trades == 4
