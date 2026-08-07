from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from types import SimpleNamespace
from uuid import uuid4

import pytest

from forex_trader.domain.enums import DecisionDisposition, Direction, OrderStatus, RiskDisposition
from forex_trader.domain.models import Candle
from forex_trader.research.backtest import BacktestTrade, OutcomeStatus
from forex_trader.research.cohorts import (
    CohortOutcomeEstimate,
    HierarchicalOutcomeModel,
    LabeledDecision,
    ResearchExpectedValueGate,
    chronological_split,
    walk_forward_cohort_calibration,
)
from forex_trader.research.evidence import (
    DecisionEvidence,
    append_decision_evidence,
    candidate_from_evidence,
    label_decision,
    load_decision_evidence,
)


BASE = datetime(2026, 1, 5, 14, 0, tzinfo=UTC)


def decision(
    index: int,
    *,
    instrument: str = "EUR_USD",
    regime: str = "trend",
    session: str = "london_new_york_overlap",
    setup: str = "zone_liquidity_sweep_reclaim",
) -> DecisionEvidence:
    signal = BASE + timedelta(minutes=5 * index)
    return DecisionEvidence(
        campaign_id="campaign-a",
        policy_fingerprint="policy-a",
        cycle=index + 1,
        instrument=instrument,
        trace_id=f"trace-{index}",
        candidate_id=str(uuid4()),
        captured_at=signal + timedelta(seconds=2),
        signal_time=signal,
        direction=Direction.LONG.value,
        disposition=DecisionDisposition.TRADE.value,
        setup_family=setup,
        setup_state="entry_confirmed",
        rejection_code=None,
        score=Decimal("0.75"),
        technical_score=Decimal("0.80"),
        fundamental_score=Decimal("0.60"),
        fundamental_confidence=Decimal("0.85"),
        entry_price=Decimal("1.1000"),
        stop_loss=Decimal("1.0990"),
        take_profit=Decimal("1.1020"),
        quote_bid=Decimal("1.0999"),
        quote_ask=Decimal("1.1000"),
        quote_time=signal + timedelta(seconds=1),
        regime=regime,
        session_phase=session,
        selected_policy="sweep_reclaim:v1",
        policy_authority="practice",
        confirmation_categories=("price", "fundamental", "execution"),
        confirmation_source_ids=("price", "macro", "broker_quote"),
        risk_disposition=RiskDisposition.GRANTED.value,
        risk_units=1000,
        risk_amount=Decimal("1"),
        order_status=None,
        execution_enabled=False,
        candidate_evidence={"zone_quality": Decimal("0.82")},
    )


def outcome(record: DecisionEvidence, *, win: bool, r: str | None = None) -> BacktestTrade:
    value = Decimal(r if r is not None else ("2" if win else "-1"))
    return BacktestTrade(
        instrument=record.instrument,
        direction=Direction.LONG,
        signal_time=record.signal_time or BASE,
        score=record.score or Decimal("0"),
        status=OutcomeStatus.WIN if win else OutcomeStatus.LOSS,
        r_multiple=value,
        bars_held=3,
        maximum_favorable_r=Decimal("2") if win else Decimal("0.3"),
        maximum_adverse_r=Decimal("0.2") if win else Decimal("1"),
    )


def test_decision_evidence_round_trip_and_trace_extraction(tmp_path) -> None:
    candidate = SimpleNamespace(
        candidate_id=uuid4(),
        signal_time=BASE,
        direction=Direction.LONG,
        disposition=DecisionDisposition.TRADE,
        setup_family="zone_liquidity_sweep_reclaim",
        setup_state="entry_confirmed",
        rejection_code=None,
        score=Decimal("0.77"),
        technical_score=Decimal("0.81"),
        fundamental_score=Decimal("0.55"),
        fundamental_confidence=Decimal("0.82"),
        entry_price=Decimal("1.1000"),
        stop_loss=Decimal("1.0990"),
        take_profit=Decimal("1.1020"),
        evidence={
            "regime": "trend",
            "selected_policy": "sweep_reclaim:v1",
            "policy_authority": "practice",
            "confirmation_categories": ["price", "fundamental", "execution"],
            "confirmation_source_ids": ["price", "macro", "broker_quote"],
            "zone_quality": Decimal("0.82"),
        },
    )
    trace = SimpleNamespace(
        trace_id=uuid4(),
        candidate=candidate,
        risk=SimpleNamespace(disposition=RiskDisposition.GRANTED, units=1500, risk_amount=Decimal("1.5")),
        order=SimpleNamespace(status=OrderStatus.PROTECTED),
        quote=SimpleNamespace(bid=Decimal("1.0999"), ask=Decimal("1.1000"), time=BASE),
        metadata={"session_phase": "london_new_york_overlap", "strategy_policy": "sweep_reclaim:v1"},
    )
    record = DecisionEvidence.from_trace(
        trace,
        campaign_id="campaign-a",
        policy_fingerprint="policy-a",
        cycle=1,
        instrument="EUR_USD",
        captured_at=BASE + timedelta(seconds=3),
        execution_enabled=True,
    )
    path = tmp_path / "decisions.jsonl"
    append_decision_evidence(path, record)
    loaded = load_decision_evidence(path)
    assert len(loaded) == 1
    assert loaded[0].regime == "trend"
    assert loaded[0].session_phase == "london_new_york_overlap"
    assert loaded[0].order_status == "protected"
    assert loaded[0].confirmation_categories == ("price", "fundamental", "execution")
    assert loaded[0].candidate_evidence["zone_quality"] == "0.82"


def test_decision_evidence_reconstructs_and_labels_candidate() -> None:
    record = decision(0)
    candidate = candidate_from_evidence(record)
    assert candidate.instrument == "EUR_USD"
    assert candidate.direction is Direction.LONG
    future = [
        Candle(
            time=BASE + timedelta(minutes=5),
            open=Decimal("1.1000"),
            high=Decimal("1.1022"),
            low=Decimal("1.0995"),
            close=Decimal("1.1020"),
        )
    ]
    labeled = label_decision(record, future)
    assert labeled.status is OutcomeStatus.WIN
    assert labeled.r_multiple == Decimal("2")


def test_chronological_split_never_shuffles_future_into_training() -> None:
    rows = [LabeledDecision(decision(index), outcome(decision(index), win=index % 2 == 0)) for index in reversed(range(10))]
    split = chronological_split(rows)
    assert len(split.train) == 6
    assert len(split.validation) == 2
    assert len(split.test) == 2
    assert split.train[-1].decision.signal_time < split.validation[0].decision.signal_time  # type: ignore[operator]
    assert split.validation[-1].decision.signal_time < split.test[0].decision.signal_time  # type: ignore[operator]


def test_hierarchical_model_uses_specific_cohort_then_falls_back() -> None:
    trend = [LabeledDecision(decision(index), outcome(decision(index), win=True)) for index in range(8)]
    range_rows = [
        LabeledDecision(
            decision(20 + index, regime="range"),
            outcome(decision(20 + index, regime="range"), win=False),
        )
        for index in range(4)
    ]
    model = HierarchicalOutcomeModel([*trend, *range_rows], minimum_cohort_trades=5, include_instrument=False)
    specific = model.estimate(decision(100))
    fallback = model.estimate(decision(101, regime="transition"))
    assert "regime=trend" in specific.cohort
    assert fallback.cohort.startswith("setup=") or fallback.cohort.startswith("all")
    assert specific.estimate.p_target_before_stop > fallback.estimate.p_target_before_stop


def test_walk_forward_calibration_uses_only_prior_history() -> None:
    rows: list[LabeledDecision] = []
    for index in range(60):
        record = decision(index)
        rows.append(LabeledDecision(record, outcome(record, win=index % 3 != 0)))
    summary = walk_forward_cohort_calibration(
        rows,
        minimum_history=10,
        minimum_cohort_trades=10,
        include_instrument=False,
    )
    assert len(summary.predictions) == 50
    assert summary.overall.count == 50
    assert Decimal("0") <= summary.overall.brier_score <= Decimal("1")
    assert Decimal("0") <= summary.overall.expected_calibration_error <= Decimal("1")


def test_research_ev_gate_requires_sample_calibration_and_conservative_edge() -> None:
    rows = [LabeledDecision(decision(index), outcome(decision(index), win=index % 4 != 0)) for index in range(80)]
    estimate = HierarchicalOutcomeModel(rows, minimum_cohort_trades=30, include_instrument=False).estimate(decision(100))
    gate = ResearchExpectedValueGate(
        minimum_sample_size=50,
        maximum_confidence_half_width=Decimal("0.20"),
        maximum_calibration_error=Decimal("0.10"),
    )
    approved = gate.evaluate(
        estimate,
        expected_gain_r=Decimal("2"),
        spread_cost_r=Decimal("0.03"),
        slippage_cost_r=Decimal("0.02"),
        calibration_error=Decimal("0.05"),
    )
    assert approved.eligible is True
    assert approved.expected_net_r > 0
    assert approved.conservative_net_r > 0

    sparse = CohortOutcomeEstimate(
        "sparse",
        estimate.estimate.__class__(
            p_target_before_stop=Decimal("0.70"),
            p_stop_before_target=Decimal("0.30"),
            expected_mfe_r=Decimal("1"),
            expected_mae_r=Decimal("0.5"),
            expected_holding_bars=Decimal("4"),
            sample_size=5,
            confidence_half_width=Decimal("0.30"),
            calibration_version="test",
        ),
    )
    denied = gate.evaluate(sparse, expected_gain_r=Decimal("2"), calibration_error=None)
    assert denied.eligible is False
    assert any("sample_size" in reason for reason in denied.reasons)
    assert "calibration_error is required" in denied.reasons


def test_invalid_evidence_file_is_rejected(tmp_path) -> None:
    path = tmp_path / "bad.jsonl"
    path.write_text('{"campaign_id":"x"}\n', encoding="utf-8")
    with pytest.raises(ValueError, match="invalid decision evidence"):
        load_decision_evidence(path)
