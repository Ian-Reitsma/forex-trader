from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

from forex_trader.research.ablations import (
    REQUIRED_ABLATION_VARIANTS,
    AblationVariant,
    MaturedAblationOutcome,
    ProspectiveAblationDecision,
)
from forex_trader.research.episode_ablations import (
    ablation_snapshot_id,
    build_episode_ablation_report,
)
from forex_trader.research.evidence import DecisionEvidence


def _decision(*, cycle: int, signal_time: datetime, zone_id: str) -> DecisionEvidence:
    return DecisionEvidence(
        campaign_id="campaign",
        policy_fingerprint="f" * 64,
        cycle=cycle,
        instrument="EUR_USD",
        trace_id=f"trace-{cycle}",
        candidate_id=f"candidate-{cycle}",
        captured_at=signal_time,
        signal_time=signal_time,
        direction="long",
        disposition="trade",
        setup_family="zone_liquidity_sweep_reclaim",
        setup_state="ENTRY_CONFIRMED",
        rejection_code=None,
        score=Decimal("0.80"),
        technical_score=Decimal("0.80"),
        fundamental_score=Decimal("0.50"),
        fundamental_confidence=Decimal("0.55"),
        entry_price=Decimal("1.1000"),
        stop_loss=Decimal("1.0990"),
        take_profit=Decimal("1.1020"),
        quote_bid=Decimal("1.0999"),
        quote_ask=Decimal("1.1001"),
        quote_time=signal_time,
        regime="normal",
        session_phase="london_open",
        selected_policy="default",
        policy_authority="production",
        confirmation_categories=("structure",),
        confirmation_source_ids=("source",),
        risk_disposition=None,
        risk_units=None,
        risk_amount=None,
        order_status=None,
        execution_enabled=False,
        candidate_evidence={"zone_id": zone_id, "liquidity_kind": "swing_low"},
    )


def _prospective(record: DecisionEvidence) -> list[ProspectiveAblationDecision]:
    snapshot_id = ablation_snapshot_id(record)
    assert snapshot_id is not None
    assert record.signal_time is not None
    return [
        ProspectiveAblationDecision(
            snapshot_id=snapshot_id,
            snapshot_payload_hash="a" * 64,
            policy_fingerprint=record.policy_fingerprint,
            instrument=record.instrument,
            signal_time=record.signal_time,
            variant=variant,
            tradeable=True,
            setup_family=record.setup_family,
            direction=record.direction,
            score=Decimal("0.8"),
            entry_price=Decimal("1.1000"),
            stop_loss=Decimal("1.0990"),
            take_profit=Decimal("1.1020"),
            rejection_code=None,
        )
        for variant in REQUIRED_ABLATION_VARIANTS
    ]


def _outcomes(record: DecisionEvidence, *, base_r: Decimal) -> list[MaturedAblationOutcome]:
    snapshot_id = ablation_snapshot_id(record)
    assert snapshot_id is not None
    rows: list[MaturedAblationOutcome] = []
    for variant in REQUIRED_ABLATION_VARIANTS:
        realized = base_r
        if variant is AblationVariant.NO_FUNDAMENTALS and record.cycle == 3:
            realized = Decimal("2")
        rows.append(
            MaturedAblationOutcome(
                snapshot_id=snapshot_id,
                snapshot_payload_hash="a" * 64,
                policy_fingerprint=record.policy_fingerprint,
                variant=variant,
                realized_r=realized,
                status="target" if realized > 0 else "stop",
                estimated_cost_r=Decimal("0.05"),
            )
        )
    return rows


def test_episode_report_uses_first_observation_and_never_hindsight_best_duplicate() -> None:
    start = datetime(2026, 8, 14, 8, 0, tzinfo=UTC)
    first_a = _decision(cycle=1, signal_time=start, zone_id="zone-a")
    duplicate_a = _decision(cycle=2, signal_time=start + timedelta(minutes=5), zone_id="zone-a")
    first_b = _decision(cycle=3, signal_time=start + timedelta(minutes=10), zone_id="zone-b")
    decisions = (first_a, duplicate_a, first_b)
    prospective = tuple(
        row for record in decisions for row in _prospective(record)
    )
    outcomes = tuple(
        [*_outcomes(first_a, base_r=Decimal("-1")),
         *_outcomes(duplicate_a, base_r=Decimal("10")),
         *_outcomes(first_b, base_r=Decimal("1"))]
    )

    report = build_episode_ablation_report(decisions, prospective, outcomes)

    assert report.raw_snapshot_count == 3
    assert report.complete_snapshot_count == 3
    assert report.structural_snapshot_count == 3
    assert report.unique_setup_episode_count == 2
    assert report.selected_matured_episode_count == 2
    assert report.duplicate_snapshot_count == 1

    by_variant = {item.variant: item for item in report.variants}
    full = by_variant[AblationVariant.FULL]
    assert full.episode_count == 2
    assert full.total_r == Decimal("0")
    assert full.expectancy_r == Decimal("0")
    assert full.wins == 1
    assert full.losses == 1

    no_fundamentals = by_variant[AblationVariant.NO_FUNDAMENTALS]
    assert no_fundamentals.total_r == Decimal("1")
    assert no_fundamentals.expectancy_r == Decimal("0.5")
