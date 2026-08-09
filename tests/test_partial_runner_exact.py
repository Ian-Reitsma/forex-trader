from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import uuid4

from forex_trader.domain.enums import DecisionDisposition, Direction
from forex_trader.domain.models import TradeCandidate
from forex_trader.research.backtest import OutcomeStatus
from forex_trader.research.partial_runner_backtest import PartialRunnerProfile
from forex_trader.research.partial_runner_exact import evaluate_exact_partial_runner
from forex_trader.research.public_history import HistoricalTick


NOW = datetime(2026, 7, 10, 12, tzinfo=UTC)
PROFILE = PartialRunnerProfile(Decimal("0.35"), Decimal("0.67"), Decimal("1.50"))


def _candidate(direction: Direction) -> TradeCandidate:
    if direction is Direction.LONG:
        entry, stop, target = Decimal("1.1001"), Decimal("1.0991"), Decimal("1.1020")
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


def test_long_partial_then_breakeven_uses_exact_tick_times() -> None:
    ticks = (
        HistoricalTick("EUR_USD", NOW, Decimal("1.1000"), Decimal("1.1001")),
        HistoricalTick("EUR_USD", NOW + timedelta(seconds=7), Decimal("1.1005"), Decimal("1.1006")),
        HistoricalTick("EUR_USD", NOW + timedelta(seconds=13), Decimal("1.1001"), Decimal("1.1002")),
    )
    result = evaluate_exact_partial_runner(
        _candidate(Direction.LONG),
        ticks,
        entry_index=0,
        profile=PROFILE,
        adverse_slippage_pips=Decimal("0"),
    )
    assert result.first_target_time == ticks[1].time
    assert result.exit_time == ticks[2].time
    assert result.trade.status is OutcomeStatus.WIN
    assert result.trade.r_multiple == Decimal("0.35") * Decimal("0.67")


def test_long_partial_then_runner_preserves_larger_winner() -> None:
    ticks = (
        HistoricalTick("EUR_USD", NOW, Decimal("1.1000"), Decimal("1.1001")),
        HistoricalTick("EUR_USD", NOW + timedelta(seconds=4), Decimal("1.1005"), Decimal("1.1006")),
        HistoricalTick("EUR_USD", NOW + timedelta(seconds=9), Decimal("1.1016"), Decimal("1.1017")),
    )
    result = evaluate_exact_partial_runner(
        _candidate(Direction.LONG),
        ticks,
        entry_index=0,
        profile=PROFILE,
        adverse_slippage_pips=Decimal("0"),
    )
    expected = Decimal("0.35") * Decimal("0.67") + Decimal("1.50") * Decimal("0.33")
    assert result.first_target_time == ticks[1].time
    assert result.exit_time == ticks[2].time
    assert result.trade.status is OutcomeStatus.WIN
    assert result.trade.r_multiple == expected


def test_short_partial_then_breakeven_uses_ask_side() -> None:
    ticks = (
        HistoricalTick("EUR_USD", NOW, Decimal("1.1000"), Decimal("1.1001")),
        HistoricalTick("EUR_USD", NOW + timedelta(seconds=3), Decimal("1.0995"), Decimal("1.0996")),
        HistoricalTick("EUR_USD", NOW + timedelta(seconds=8), Decimal("1.0999"), Decimal("1.1000")),
    )
    result = evaluate_exact_partial_runner(
        _candidate(Direction.SHORT),
        ticks,
        entry_index=0,
        profile=PROFILE,
        adverse_slippage_pips=Decimal("0"),
    )
    assert result.first_target_time == ticks[1].time
    assert result.exit_time == ticks[2].time
    assert result.trade.r_multiple == Decimal("0.35") * Decimal("0.67")


def test_structural_stop_before_partial_is_full_loss() -> None:
    ticks = (
        HistoricalTick("EUR_USD", NOW, Decimal("1.1000"), Decimal("1.1001")),
        HistoricalTick("EUR_USD", NOW + timedelta(seconds=5), Decimal("1.0990"), Decimal("1.0991")),
    )
    result = evaluate_exact_partial_runner(
        _candidate(Direction.LONG),
        ticks,
        entry_index=0,
        profile=PROFILE,
        adverse_slippage_pips=Decimal("0"),
    )
    assert result.first_target_time is None
    assert result.exit_time == ticks[1].time
    assert result.trade.status is OutcomeStatus.LOSS
    assert result.trade.r_multiple <= Decimal("-1")
