from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import uuid4

import pytest

from forex_trader.domain.enums import DecisionDisposition, Direction
from forex_trader.domain.models import Candle, TradeCandidate
from forex_trader.research.backtest import OutcomeStatus
from forex_trader.research.management import (
    HALF_AT_ONE_R_RUNNER,
    STRUCTURAL_SINGLE_TARGET,
    ManagementPolicy,
    ManagementScenario,
    compare_management_policies,
    evaluate_management_outcome,
    summarize_management,
)


def candidate(direction: Direction = Direction.LONG) -> TradeCandidate:
    return TradeCandidate(
        candidate_id=uuid4(),
        instrument="EUR_USD",
        direction=direction,
        disposition=DecisionDisposition.TRADE,
        score=Decimal("0.8"),
        entry_price=Decimal("1.1000"),
        stop_loss=Decimal("1.0990") if direction is Direction.LONG else Decimal("1.1010"),
        take_profit=Decimal("1.1020") if direction is Direction.LONG else Decimal("1.0980"),
        technical_score=Decimal("0.8"),
        fundamental_score=Decimal("0.5"),
        reasons=(),
        signal_time=datetime(2026, 8, 7, 12, tzinfo=UTC),
    )


def candle(index: int, *, open_: str, high: str, low: str, close: str) -> Candle:
    return Candle(
        datetime(2026, 8, 7, 12, tzinfo=UTC) + timedelta(minutes=5 * index),
        Decimal(open_),
        Decimal(high),
        Decimal(low),
        Decimal(close),
    )


def test_single_target_policy_matches_structural_win_and_gap_loss() -> None:
    win = evaluate_management_outcome(
        candidate(),
        [candle(1, open_="1.1000", high="1.1021", low="1.0995", close="1.1020")],
        STRUCTURAL_SINGLE_TARGET,
    )
    assert win.status is OutcomeStatus.WIN
    assert win.r_multiple == Decimal("2")
    assert win.exit_reason == "structural_target"

    gap = evaluate_management_outcome(
        candidate(),
        [candle(1, open_="1.0980", high="1.0988", low="1.0975", close="1.0980")],
        STRUCTURAL_SINGLE_TARGET,
    )
    assert gap.status is OutcomeStatus.LOSS
    assert gap.r_multiple < Decimal("-1")
    assert gap.exit_reason == "gap_stop"


def test_half_at_one_r_then_breakeven_runner() -> None:
    trade = evaluate_management_outcome(
        candidate(),
        [
            candle(1, open_="1.1000", high="1.1012", low="1.0995", close="1.1010"),
            candle(2, open_="1.1010", high="1.1013", low="1.0999", close="1.1002"),
        ],
        HALF_AT_ONE_R_RUNNER,
    )
    assert trade.partial_taken is True
    assert trade.partial_component_r == Decimal("0.5")
    assert trade.runner_component_r == Decimal("0")
    assert trade.r_multiple == Decimal("0.5")
    assert trade.status is OutcomeStatus.WIN
    assert trade.exit_reason == "runner_stop"


def test_partial_then_structural_target_realizes_weighted_r() -> None:
    trade = evaluate_management_outcome(
        candidate(),
        [candle(1, open_="1.1000", high="1.1022", low="1.0995", close="1.1020")],
        HALF_AT_ONE_R_RUNNER,
    )
    assert trade.partial_taken is True
    assert trade.partial_component_r == Decimal("0.5")
    assert trade.runner_component_r == Decimal("1.0")
    assert trade.r_multiple == Decimal("1.5")
    assert trade.exit_reason == "partial_then_structural_target"


def test_same_bar_stop_and_partial_is_conservatively_stopped_first() -> None:
    trade = evaluate_management_outcome(
        candidate(),
        [candle(1, open_="1.1000", high="1.1012", low="1.0988", close="1.1005")],
        HALF_AT_ONE_R_RUNNER,
    )
    assert trade.status is OutcomeStatus.LOSS
    assert trade.r_multiple == Decimal("-1")
    assert trade.partial_taken is False
    assert trade.ambiguous_bar is True


def test_short_runner_management_is_directionally_symmetric() -> None:
    trade = evaluate_management_outcome(
        candidate(Direction.SHORT),
        [
            candle(1, open_="1.1000", high="1.1005", low="1.0988", close="1.0990"),
            candle(2, open_="1.0990", high="1.1001", low="1.0987", close="1.0998"),
        ],
        HALF_AT_ONE_R_RUNNER,
    )
    assert trade.partial_taken is True
    assert trade.r_multiple == Decimal("0.5")


def test_management_timeout_marks_runner_and_costs_are_adverse() -> None:
    scenario = [candle(1, open_="1.1000", high="1.1008", low="1.0995", close="1.1006")]
    clean = evaluate_management_outcome(candidate(), scenario, STRUCTURAL_SINGLE_TARGET)
    stressed = evaluate_management_outcome(
        candidate(),
        scenario,
        STRUCTURAL_SINGLE_TARGET,
        spread_pips=Decimal("1"),
        exit_slippage_pips=Decimal("0.2"),
    )
    assert clean.status is OutcomeStatus.TIMEOUT
    assert stressed.r_multiple < clean.r_multiple


def test_compare_management_policies_reports_expectancy_drawdown_and_partial_rate() -> None:
    scenarios = [
        ManagementScenario(
            candidate(),
            (candle(1, open_="1.1000", high="1.1022", low="1.0995", close="1.1020"),),
        ),
        ManagementScenario(
            candidate(),
            (candle(2, open_="1.1000", high="1.1005", low="1.0988", close="1.0990"),),
        ),
    ]
    reports = compare_management_policies(
        scenarios,
        [STRUCTURAL_SINGLE_TARGET, HALF_AT_ONE_R_RUNNER],
    )
    assert len(reports) == 2
    assert reports[0].trades == 2
    assert reports[1].partial_frequency > 0
    assert reports[0].max_drawdown_r >= 0


def test_management_policy_and_evaluator_validate_inputs() -> None:
    with pytest.raises(ValueError, match="name"):
        ManagementPolicy("")
    with pytest.raises(ValueError, match="partial_fraction"):
        ManagementPolicy("bad", partial_at_r=Decimal("1"), partial_fraction=Decimal("1"))
    with pytest.raises(ValueError, match="positive partial_at_r"):
        ManagementPolicy("bad", partial_fraction=Decimal("0.5"))
    with pytest.raises(ValueError, match="partial_at_r requires"):
        ManagementPolicy("bad", partial_at_r=Decimal("1"))
    with pytest.raises(ValueError, match="breakeven"):
        ManagementPolicy("bad", move_stop_to_break_even=True)
    with pytest.raises(ValueError, match="below the structural target"):
        evaluate_management_outcome(
            candidate(),
            [candle(1, open_="1.1000", high="1.1010", low="1.0995", close="1.1005")],
            ManagementPolicy(
                "too-late-partial",
                partial_at_r=Decimal("2"),
                partial_fraction=Decimal("0.5"),
            ),
        )
    with pytest.raises(ValueError, match="at least one management scenario"):
        compare_management_policies([], [STRUCTURAL_SINGLE_TARGET])
    with pytest.raises(ValueError, match="at least one management policy"):
        compare_management_policies(
            [ManagementScenario(candidate(), tuple())],
            [],
        )
    with pytest.raises(ValueError, match="managed trade"):
        summarize_management([], policy_name="none")
