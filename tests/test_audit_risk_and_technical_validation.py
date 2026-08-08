from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import uuid4

import pytest

from forex_trader.domain.enums import DecisionDisposition, Direction, RiskDisposition
from forex_trader.domain.macro_factor_risk import MacroFactorClusterGuard, default_macro_factor_map
from forex_trader.domain.models import AccountSnapshot, Candle, Quote, TradeCandidate
from forex_trader.domain.portfolio import OpenPosition
from forex_trader.domain.risk_advanced import EnhancedRiskPolicy
from forex_trader.ingestion.providers import OrderFlowSnapshot
from forex_trader.research.flow_strategies import (
    FlowDivergenceResearchPolicy,
    ResearchFlowState,
    VwapRepositioningResearchPolicy,
)
from forex_trader.research.technical_annotation import (
    BinaryTechnicalLabel,
    TechnicalAdjudication,
    TechnicalDirectionLabel,
    TechnicalGroundTruthLabel,
    TechnicalReviewerSubmission,
    TechnicalWindow,
    build_blinded_technical_batch,
    finalize_technical_labels,
    split_technical_calibration_holdout,
)

NOW = datetime(2026, 8, 7, 14, 0, tzinfo=UTC)


def _candidate(instrument: str = "EUR_USD") -> TradeCandidate:
    return TradeCandidate(
        candidate_id=uuid4(),
        instrument=instrument,
        direction=Direction.LONG,
        disposition=DecisionDisposition.TRADE,
        score=Decimal("0.9"),
        entry_price=Decimal("1.1000"),
        stop_loss=Decimal("1.0990"),
        take_profit=Decimal("1.1030"),
        technical_score=Decimal("0.9"),
        fundamental_score=Decimal("0.7"),
        reasons=(),
        signal_time=NOW,
        execution_key="test",
    )


def _account() -> AccountSnapshot:
    return AccountSnapshot(
        account_id="practice",
        currency="USD",
        balance=Decimal("100000"),
        nav=Decimal("100000"),
        margin_available=Decimal("100000"),
        open_position_count=2,
    )


def _conversion(_source: str, _target: str) -> Decimal:
    return Decimal("1")


def test_macro_factor_guard_blocks_shared_macro_thesis_even_without_correlation() -> None:
    guard = MacroFactorClusterGuard(
        default_macro_factor_map(),
        maximum_factor_exposure_fraction=Decimal("2.5"),
    )
    positions = [
        OpenPosition("GBP_USD", long_units=Decimal("100000"), long_average_price=Decimal("1.30")),
        OpenPosition("AUD_USD", long_units=Decimal("100000"), long_average_price=Decimal("0.70")),
    ]
    marks = {
        "GBP_USD": Decimal("1.30"),
        "AUD_USD": Decimal("0.70"),
    }
    decision = guard.evaluate_candidate(
        candidate_instrument="EUR_USD",
        candidate_direction=Direction.LONG,
        candidate_units=100_000,
        candidate_entry_price=Decimal("1.10"),
        positions=positions,
        account_currency="USD",
        capital_base=Decimal("100000"),
        conversion_rate=_conversion,
        mark_price=lambda instrument: marks.get(instrument),
    )
    assert decision.blocked
    assert decision.maximum_factor in {"usd_macro", "usd_rates"}
    assert decision.maximum_factor_exposure == Decimal("310000.00")
    assert "macro factor exposure limit exceeded" in str(decision.reason)


def test_macro_factor_guard_fails_closed_for_unclassified_pair() -> None:
    guard = MacroFactorClusterGuard(default_macro_factor_map())
    decision = guard.evaluate_candidate(
        candidate_instrument="XAU_USD",
        candidate_direction=Direction.LONG,
        candidate_units=1,
        candidate_entry_price=Decimal("2000"),
        positions=(),
        account_currency="USD",
        capital_base=Decimal("100000"),
        conversion_rate=_conversion,
        mark_price=lambda _instrument: None,
    )
    assert decision.blocked
    assert decision.report.unclassified_instruments == ("XAU_USD",)


def test_enhanced_risk_policy_enforces_macro_factor_guard() -> None:
    guard = MacroFactorClusterGuard(
        default_macro_factor_map(),
        maximum_factor_exposure_fraction=Decimal("2.5"),
    )
    policy = EnhancedRiskPolicy(
        max_open_positions=5,
        max_gross_exposure_fraction=Decimal("10"),
        max_currency_exposure_fraction=Decimal("10"),
        macro_factor_guard=guard,
    )
    positions = [
        OpenPosition("GBP_USD", long_units=Decimal("100000"), long_average_price=Decimal("1.30")),
        OpenPosition("AUD_USD", long_units=Decimal("100000"), long_average_price=Decimal("0.70")),
    ]
    marks = {
        "GBP_USD": Decimal("1.30"),
        "AUD_USD": Decimal("0.70"),
    }
    result = policy.authorize(
        _candidate(),
        _account(),
        Quote("EUR_USD", Decimal("1.0999"), Decimal("1.1001"), NOW),
        positions=positions,
        conversion_rate=_conversion,
        mark_price=lambda instrument: marks.get(instrument),
        margin_rate=Decimal("0.01"),
    )
    assert result.disposition is RiskDisposition.DENIED
    assert "macro factor exposure limit exceeded" in "|".join(result.reasons)


def _window(index: int) -> TechnicalWindow:
    start = NOW - timedelta(days=10) + timedelta(hours=index * 12)
    candles = tuple(
        Candle(
            time=start + timedelta(minutes=5 * offset),
            open=Decimal("1.1000") + Decimal(offset) * Decimal("0.0001"),
            high=Decimal("1.1003") + Decimal(offset) * Decimal("0.0001"),
            low=Decimal("1.0998") + Decimal(offset) * Decimal("0.0001"),
            close=Decimal("1.1001") + Decimal(offset) * Decimal("0.0001"),
            volume=100 + offset,
            complete=True,
        )
        for offset in range(8)
    )
    return TechnicalWindow("EUR_USD", "M5", candles)


def _label(direction: TechnicalDirectionLabel = TechnicalDirectionLabel.LONG) -> TechnicalGroundTruthLabel:
    return TechnicalGroundTruthLabel(
        zone=BinaryTechnicalLabel.PRESENT,
        liquidity_sweep=BinaryTechnicalLabel.PRESENT,
        structure_shift=BinaryTechnicalLabel.PRESENT,
        retest=BinaryTechnicalLabel.PRESENT,
        direction=direction,
    )


def test_blinded_technical_batch_contains_raw_chart_data_only_and_fixed_holdout() -> None:
    batch = build_blinded_technical_batch((_window(index) for index in range(6)), frozen_as_of=NOW)
    public = batch.public_payload()
    assert len(public["packets"]) == 6  # type: ignore[arg-type]
    serialized = str(public).lower()
    for forbidden in ("selected_policy", "candidate", "take_profit", "stop_loss", "pnl", "outcome"):
        assert forbidden not in serialized
    manifest = split_technical_calibration_holdout(batch)
    assert len(manifest.calibration_packet_ids) == 4
    assert len(manifest.holdout_packet_ids) == 2
    assert not set(manifest.calibration_packet_ids) & set(manifest.holdout_packet_ids)


def test_technical_ground_truth_requires_independent_adjudication_on_disagreement() -> None:
    batch = build_blinded_technical_batch([_window(0)], frozen_as_of=NOW)
    packet_id = batch.packets[0].packet_id
    reviews = [
        TechnicalReviewerSubmission(packet_id, "expert-a", _label(TechnicalDirectionLabel.LONG)),
        TechnicalReviewerSubmission(packet_id, "expert-b", _label(TechnicalDirectionLabel.SHORT)),
    ]
    with pytest.raises(ValueError, match="requires adjudication"):
        finalize_technical_labels(batch, reviews)

    corpus = finalize_technical_labels(
        batch,
        reviews,
        [TechnicalAdjudication(packet_id, "expert-c", _label(TechnicalDirectionLabel.AMBIGUOUS))],
    )
    assert len(corpus.labels) == 1
    assert not corpus.labels[0].agreement
    assert corpus.labels[0].adjudicator_id == "expert-c"
    assert corpus.labels[0].label.direction is TechnicalDirectionLabel.AMBIGUOUS


def _flow(**overrides: object) -> OrderFlowSnapshot:
    values: dict[str, object] = {
        "instrument": "EUR_USD",
        "observed_at": NOW,
        "source": "cme_fx_futures",
        "directional_pressure": Decimal("0.60"),
        "vwap": Decimal("1.1000"),
        "confidence": Decimal("0.90"),
    }
    values.update(overrides)
    return OrderFlowSnapshot(**values)  # type: ignore[arg-type]


def test_flow_divergence_state_machine_is_research_only_and_requires_structure() -> None:
    policy = FlowDivergenceResearchPolicy()
    armed = policy.evaluate(
        _flow(),
        price_change=Decimal("-0.0004"),
        pip_size=Decimal("0.0001"),
        at_key_location=True,
        structure_shift=False,
    )
    assert armed.state is ResearchFlowState.ARMED
    assert armed.direction is Direction.LONG
    assert not armed.executable

    confirmed = policy.evaluate(
        _flow(),
        price_change=Decimal("-0.0004"),
        pip_size=Decimal("0.0001"),
        at_key_location=True,
        structure_shift=True,
    )
    assert confirmed.state is ResearchFlowState.CONFIRMED
    assert not confirmed.executable


def test_vwap_repositioning_requires_centralized_source_and_flow_alignment() -> None:
    policy = VwapRepositioningResearchPolicy()
    invalid = policy.evaluate(
        _flow(source="broker_tick_proxy"),
        previous_price=Decimal("1.0990"),
        current_price=Decimal("1.1010"),
        pip_size=Decimal("0.0001"),
        structure_shift=True,
    )
    assert invalid.state is ResearchFlowState.INELIGIBLE

    confirmed = policy.evaluate(
        _flow(),
        previous_price=Decimal("1.0990"),
        current_price=Decimal("1.1010"),
        pip_size=Decimal("0.0001"),
        structure_shift=True,
    )
    assert confirmed.state is ResearchFlowState.CONFIRMED
    assert confirmed.direction is Direction.LONG
    assert not confirmed.executable
