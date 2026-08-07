from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

from forex_trader.adapters.synthetic import SyntheticMarketData
from forex_trader.domain.decision_components import DecisionComponentPolicy
from forex_trader.domain.enums import DecisionDisposition
from forex_trader.domain.fusion import RegimeAwareSignalFusionPolicy
from forex_trader.domain.models import FundamentalAssessment
from forex_trader.domain.technicals import assess_technicals
from forex_trader.research.ablations import AblationVariant
from forex_trader.research.production_signal_ablation import (
    ProductionSignalAblationEvaluator,
    freeze_production_signal_snapshot,
)


def _fundamental(*, differential: str = "0.10", confidence: str = "0.80") -> FundamentalAssessment:
    value = Decimal(differential)
    return FundamentalAssessment(
        instrument="EUR_USD",
        base_score=value,
        quote_score=Decimal("0"),
        differential=value,
        confidence=Decimal(confidence),
        reasons=("frozen point-in-time macro assessment",),
    )


def _snapshot(
    *,
    anchor: datetime = datetime(2025, 1, 15, 19, 0, tzinfo=UTC),
    fundamental: FundamentalAssessment | None = None,
):  # type: ignore[no-untyped-def]
    market = SyntheticMarketData(anchor=anchor)
    lower = market.candles("EUR_USD", "M5", 200)
    higher = market.candles("EUR_USD", "H1", 200)
    quote = market.quote("EUR_USD")
    return (
        freeze_production_signal_snapshot(
            snapshot_id=f"snapshot-{anchor.isoformat()}",
            policy_fingerprint="policy-v0.7.7",
            instrument="EUR_USD",
            lower_candles=lower,
            higher_candles=higher,
            quote=quote,
            fundamental=fundamental or _fundamental(),
            maximum_spread_pips=Decimal("2.0"),
        ),
        lower,
        higher,
        quote,
    )


def test_full_variant_matches_direct_production_signal_path() -> None:
    snapshot, lower, higher, quote = _snapshot()
    fundamental = _fundamental()
    policy = RegimeAwareSignalFusionPolicy()
    technical = assess_technicals("EUR_USD", lower, higher)
    direct = policy.evaluate(technical, fundamental, quote, maximum_spread_pips=Decimal("2.0"))

    row = ProductionSignalAblationEvaluator(policy).evaluate_full(snapshot)

    assert row.variant is AblationVariant.FULL
    assert row.tradeable is (direct.disposition is DecisionDisposition.TRADE)
    assert row.setup_family == direct.setup_family
    assert row.direction == direct.direction.value
    assert row.score == direct.score
    assert row.entry_price == direct.entry_price
    assert row.stop_loss == direct.stop_loss
    assert row.take_profit == direct.take_profit
    assert row.rejection_code == direct.rejection_code


def test_no_fundamentals_removes_real_conflict_gate_on_same_snapshot() -> None:
    hostile = _fundamental(differential="-1.0", confidence="1.0")
    snapshot, _, _, _ = _snapshot(fundamental=hostile)
    rows = {row.variant: row for row in ProductionSignalAblationEvaluator(RegimeAwareSignalFusionPolicy()).adapter().collect(snapshot)}

    assert rows[AblationVariant.FULL].tradeable is False
    assert rows[AblationVariant.FULL].rejection_code == "FUNDAMENTAL_CONFLICT"
    assert rows[AblationVariant.NO_FUNDAMENTALS].tradeable is True
    assert rows[AblationVariant.NO_FUNDAMENTALS].rejection_code is None


def test_flow_zone_quality_and_retest_controls_change_real_technical_inputs() -> None:
    _, lower, higher, _ = _snapshot()
    full = assess_technicals("EUR_USD", lower, higher)
    no_flow = assess_technicals(
        "EUR_USD",
        lower,
        higher,
        components=DecisionComponentPolicy(flow=False),
    )
    no_zone_quality = assess_technicals(
        "EUR_USD",
        lower,
        higher,
        components=DecisionComponentPolicy(zone_quality=False),
    )
    no_retest = assess_technicals(
        "EUR_USD",
        lower,
        higher,
        components=DecisionComponentPolicy(retest=False),
    )

    assert full.flow_source != "none"
    assert no_flow.flow_source == "none"
    assert no_flow.flow_pressure == 0
    assert no_flow.score <= full.score
    assert no_zone_quality.score < full.score
    assert no_retest.retest_confirmed is full.retest_confirmed
    assert no_retest.setup_state == "entry_confirmed"
    if full.retest_confirmed:
        assert no_retest.score == full.score - Decimal("0.10")


def test_no_session_removes_real_session_score_and_regime_input() -> None:
    snapshot, lower, higher, _ = _snapshot(anchor=datetime(2025, 1, 15, 10, 30, tzinfo=UTC))
    full = assess_technicals("EUR_USD", lower, higher)
    no_session = assess_technicals(
        "EUR_USD",
        lower,
        higher,
        components=DecisionComponentPolicy(session=False),
    )
    assert full.score == no_session.score + Decimal("0.04")

    rows = {row.variant: row for row in ProductionSignalAblationEvaluator(RegimeAwareSignalFusionPolicy()).adapter().collect(snapshot)}
    assert rows[AblationVariant.FULL].snapshot_payload_hash == rows[AblationVariant.NO_SESSION].snapshot_payload_hash
    assert rows[AblationVariant.FULL].signal_time == rows[AblationVariant.NO_SESSION].signal_time


def test_adapter_collects_all_real_variants_on_one_frozen_payload() -> None:
    snapshot, _, _, _ = _snapshot()
    rows = ProductionSignalAblationEvaluator(RegimeAwareSignalFusionPolicy()).adapter().collect(snapshot)

    assert {row.variant for row in rows} == set(AblationVariant)
    assert {row.snapshot_id for row in rows} == {snapshot.snapshot_id}
    assert {row.snapshot_payload_hash for row in rows} == {snapshot.payload_hash}
    assert {row.policy_fingerprint for row in rows} == {snapshot.policy_fingerprint}
    assert {row.signal_time for row in rows} == {snapshot.signal_time}
