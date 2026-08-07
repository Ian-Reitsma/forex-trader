from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

from forex_trader.domain.enums import Direction
from forex_trader.domain.models import Candle
from forex_trader.research.advanced import EmpiricalOutcomeModel, expected_net_r
from forex_trader.research.backtest import BacktestTrade, OutcomeStatus
from forex_trader.research.dataset import (
    OutcomeEvidence,
    append_outcome_evidence,
    join_labeled_decisions,
    label_mature_decisions,
    load_outcome_evidence,
)
from forex_trader.research.evidence import DecisionEvidence


BASE = datetime(2026, 1, 5, 14, 0, tzinfo=UTC)


def _decision(index: int = 0) -> DecisionEvidence:
    signal = BASE + timedelta(minutes=5 * index)
    return DecisionEvidence(
        campaign_id="campaign-a",
        policy_fingerprint="policy-a",
        cycle=index + 1,
        instrument="EUR_USD",
        trace_id=f"trace-{index}",
        candidate_id=f"candidate-{index}",
        captured_at=signal,
        signal_time=signal,
        direction="long",
        disposition="trade",
        setup_family="zone_liquidity_sweep_reclaim",
        setup_state="entry_confirmed",
        rejection_code=None,
        score=Decimal("0.75"),
        technical_score=Decimal("0.8"),
        fundamental_score=Decimal("0.6"),
        fundamental_confidence=Decimal("0.8"),
        entry_price=Decimal("1.1000"),
        stop_loss=Decimal("1.0990"),
        take_profit=Decimal("1.1020"),
        quote_bid=Decimal("1.0999"),
        quote_ask=Decimal("1.1000"),
        quote_time=signal,
        regime="trend",
        session_phase="london",
        selected_policy="sweep_reclaim:v1",
        policy_authority="practice",
        confirmation_categories=("price", "fundamental"),
        confirmation_source_ids=("price", "macro"),
        risk_disposition="granted",
        risk_units=1000,
        risk_amount=Decimal("1"),
        order_status=None,
        execution_enabled=False,
        candidate_evidence={},
    )


def _candle(index: int, *, high: str = "1.1005", low: str = "1.0995", close: str = "1.1001") -> Candle:
    return Candle(
        time=BASE + timedelta(minutes=5 * index),
        open=Decimal("1.1000"),
        high=Decimal(high),
        low=Decimal(low),
        close=Decimal(close),
    )


def _trade(status: OutcomeStatus, r: str) -> BacktestTrade:
    return BacktestTrade(
        instrument="EUR_USD",
        direction=Direction.LONG,
        signal_time=BASE,
        score=Decimal("0.75"),
        status=status,
        r_multiple=Decimal(r),
        bars_held=4,
    )


def test_positive_timeout_is_not_mislabeled_as_target_hit() -> None:
    sample = [_trade(OutcomeStatus.TIMEOUT, "0.4") for _ in range(20)]
    sample.extend([_trade(OutcomeStatus.WIN, "2"), _trade(OutcomeStatus.LOSS, "-1")])
    estimate = EmpiricalOutcomeModel().estimate(sample)
    assert estimate.p_timeout > estimate.p_target_before_stop
    assert estimate.p_timeout > estimate.p_stop_before_target
    assert estimate.p_target_before_stop < Decimal("0.2")
    assert estimate.p_target_before_stop + estimate.p_stop_before_target + estimate.p_timeout == Decimal("1")


def test_expected_value_includes_empirical_timeout_exit_return() -> None:
    positive_timeouts = EmpiricalOutcomeModel().estimate([_trade(OutcomeStatus.TIMEOUT, "0.5") for _ in range(10)])
    negative_timeouts = EmpiricalOutcomeModel().estimate([_trade(OutcomeStatus.TIMEOUT, "-0.5") for _ in range(10)])
    positive_ev = expected_net_r(positive_timeouts, expected_gain_r=Decimal("2"))
    negative_ev = expected_net_r(negative_timeouts, expected_gain_r=Decimal("2"))
    assert positive_ev > negative_ev


def test_partial_unresolved_horizon_is_not_written_as_timeout() -> None:
    record = _decision()
    candles = [_candle(index) for index in range(1, 4)]
    outcomes = label_mature_decisions(
        [record],
        {"EUR_USD": candles},
        maximum_bars=5,
        labeled_at=candles[-1].time,
    )
    assert outcomes == ()


def test_terminal_target_can_be_labeled_before_full_horizon() -> None:
    record = _decision()
    candles = [_candle(1, high="1.1023", low="1.0997", close="1.1020")]
    outcomes = label_mature_decisions(
        [record],
        {"EUR_USD": candles},
        maximum_bars=24,
        labeled_at=candles[-1].time,
    )
    assert len(outcomes) == 1
    assert outcomes[0].status == OutcomeStatus.WIN.value


def test_outcome_evidence_round_trip_and_join(tmp_path) -> None:
    decision = _decision()
    trade = _trade(OutcomeStatus.WIN, "2")
    outcome = OutcomeEvidence.from_trade(
        decision,
        trade,
        labeled_at=BASE + timedelta(minutes=5),
        label_policy="test-v1",
    )
    path = tmp_path / "outcomes.jsonl"
    append_outcome_evidence(path, outcome)
    loaded = load_outcome_evidence(path)
    joined = join_labeled_decisions([decision], loaded)
    assert len(joined) == 1
    assert joined[0].outcome.status is OutcomeStatus.WIN
    assert joined[0].outcome.r_multiple == Decimal("2")
