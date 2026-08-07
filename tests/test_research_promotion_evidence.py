from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from forex_trader.research.evidence import DecisionEvidence
from forex_trader.research.promotion_evidence import (
    AblationEvidence,
    PhaseDHoldoutEvidence,
    ReplayReproducibilityEvidence,
    ResearchPromotionDisposition,
    assess_research_promotion,
    evidence_from_research_report,
)


BASE = datetime(2026, 1, 5, 14, 0, tzinfo=UTC)
SETUP = "zone_continuation"
POLICY = "policy-v1"
DATASET = "dataset-v1"
ABLATION_NAMES = (
    "no_fundamentals",
    "no_flow",
    "no_session",
    "no_zone_quality",
    "no_retest",
)


def decision(index: int, *, error: bool = False) -> DecisionEvidence:
    signal = BASE + timedelta(minutes=5 * index)
    return DecisionEvidence(
        campaign_id="campaign-a",
        policy_fingerprint=POLICY,
        cycle=index + 1,
        instrument="EUR_USD",
        trace_id=f"trace-{index}",
        candidate_id=f"candidate-{index}",
        captured_at=signal,
        signal_time=signal,
        direction="long",
        disposition="trade",
        setup_family=SETUP,
        setup_state="entry_confirmed",
        rejection_code=None,
        score=Decimal("0.75"),
        technical_score=Decimal("0.8"),
        fundamental_score=Decimal("0.6"),
        fundamental_confidence=Decimal("0.8"),
        entry_price=Decimal("1.1000"),
        stop_loss=Decimal("1.0990"),
        take_profit=Decimal("1.1030"),
        quote_bid=Decimal("1.0999"),
        quote_ask=Decimal("1.1000"),
        quote_time=signal,
        regime="trend",
        session_phase="london",
        selected_policy="zone_continuation:v1",
        policy_authority="shadow",
        confirmation_categories=("price", "fundamental"),
        confirmation_source_ids=("price", "macro"),
        risk_disposition=None,
        risk_units=None,
        risk_amount=None,
        order_status=None,
        execution_enabled=False,
        candidate_evidence={},
        error_type="ProviderError" if error else None,
        error_message="synthetic provider error" if error else None,
    )


def report() -> dict[str, object]:
    return {
        "research_only": True,
        "execution_authority": False,
        "policy_fingerprint": POLICY,
        "setup_family_filter": SETUP,
        "setup_families_observed": [SETUP],
        "dataset": {
            "dataset_id": DATASET,
            "decision_sha256": "a" * 64,
            "outcome_sha256": "b" * 64,
            "labeled_trades": 250,
            "train": 150,
            "validation": 50,
            "test": 50,
        },
        "validation_calibration": {
            "count": 50,
            "brier_score": "0.20",
            "expected_calibration_error": "0.05",
            "cohorts": {"setup=zone_continuation": 50},
        },
        "untouched_test": {
            "all": {
                "trades": 50,
                "win_rate": "0.58",
                "expectancy_r": "0.25",
                "max_drawdown_r": "4",
                "total_r": "12.5",
            },
            "ev_eligible": {
                "trades": 30,
                "win_rate": "0.63",
                "expectancy_r": "0.40",
                "max_drawdown_r": "2.5",
                "total_r": "12",
            },
            "eligible_count": 30,
            "rejected_count": 20,
        },
    }


def ablations(*, dataset_id: str = DATASET, harmful: str | None = None) -> tuple[AblationEvidence, ...]:
    rows = []
    for name in ABLATION_NAMES:
        rows.append(
            AblationEvidence(
                name=name,
                full_expectancy_r=Decimal("0.25"),
                ablated_expectancy_r=Decimal("0.35") if name == harmful else Decimal("0.20"),
                sample_size=50,
                dataset_id=dataset_id,
            )
        )
    return tuple(rows)


def replay(*hashes: str) -> ReplayReproducibilityEvidence:
    return ReplayReproducibilityEvidence("manifest-hash", tuple(hashes))


def build_evidence(
    *,
    ablation_rows: tuple[AblationEvidence, ...] = (),
    replay_evidence: ReplayReproducibilityEvidence | None = None,
    phase_d: PhaseDHoldoutEvidence | None = None,
    errors: int = 0,
):  # type: ignore[no-untyped-def]
    decisions = [decision(index, error=index < errors) for index in range(250)]
    return evidence_from_research_report(
        report(),
        decisions,
        setup_family=SETUP,
        dataset_id=DATASET,
        ablations=ablation_rows,
        replay=replay_evidence,
        phase_d=phase_d,
    )


def test_missing_ablations_and_replay_is_insufficient_not_shadow_candidate() -> None:
    assessment = assess_research_promotion(build_evidence())
    assert assessment.disposition is ResearchPromotionDisposition.INSUFFICIENT_EVIDENCE
    assert "replay_reproducibility" in assessment.missing_evidence
    assert all(f"ablation:{name}" in assessment.missing_evidence for name in ABLATION_NAMES)
    assert assessment.practice_authority_changed is False


def test_complete_positive_bundle_can_only_nominate_shadow_candidate() -> None:
    evidence = build_evidence(
        ablation_rows=ablations(),
        replay_evidence=replay("same", "same"),
    )
    assessment = assess_research_promotion(evidence)
    assert assessment.disposition is ResearchPromotionDisposition.SHADOW_CANDIDATE
    assert assessment.shadow_candidate is True
    assert assessment.hard_failures == ()
    assert assessment.missing_evidence == ()
    assert assessment.practice_authority_changed is False


def test_ablation_that_materially_beats_full_policy_rejects_bundle() -> None:
    assessment = assess_research_promotion(
        build_evidence(
            ablation_rows=ablations(harmful="no_fundamentals"),
            replay_evidence=replay("same", "same"),
        )
    )
    assert assessment.disposition is ResearchPromotionDisposition.REJECTED
    assert any("no_fundamentals" in item and "outperforms" in item for item in assessment.hard_failures)


def test_ablation_dataset_mismatch_rejects_bundle() -> None:
    assessment = assess_research_promotion(
        build_evidence(
            ablation_rows=ablations(dataset_id="different-dataset"),
            replay_evidence=replay("same", "same"),
        )
    )
    assert assessment.disposition is ResearchPromotionDisposition.REJECTED
    assert any("dataset_id mismatch" in item for item in assessment.hard_failures)


def test_nondeterministic_replay_rejects_bundle() -> None:
    assessment = assess_research_promotion(
        build_evidence(
            ablation_rows=ablations(),
            replay_evidence=replay("first", "second"),
        )
    )
    assert assessment.disposition is ResearchPromotionDisposition.REJECTED
    assert "replay result hashes differ under the same manifest" in assessment.hard_failures


def test_phase_d_change_requires_confirmed_paired_holdout() -> None:
    evidence = build_evidence(
        ablation_rows=ablations(),
        replay_evidence=replay("same", "same"),
    )
    missing = assess_research_promotion(evidence, proposed_phase_d_policy="limit-0.25r-structural")
    assert missing.disposition is ResearchPromotionDisposition.INSUFFICIENT_EVIDENCE
    assert "phase_d_holdout:limit-0.25r-structural" in missing.missing_evidence

    confirmed_evidence = build_evidence(
        ablation_rows=ablations(),
        replay_evidence=replay("same", "same"),
        phase_d=PhaseDHoldoutEvidence(
            "limit-0.25r-structural",
            True,
            40,
            Decimal("0.07"),
        ),
    )
    confirmed = assess_research_promotion(
        confirmed_evidence,
        proposed_phase_d_policy="limit-0.25r-structural",
    )
    assert confirmed.disposition is ResearchPromotionDisposition.SHADOW_CANDIDATE


def test_excess_provider_error_rate_rejects_otherwise_good_bundle() -> None:
    assessment = assess_research_promotion(
        build_evidence(
            ablation_rows=ablations(),
            replay_evidence=replay("same", "same"),
            errors=5,
        )
    )
    assert assessment.disposition is ResearchPromotionDisposition.REJECTED
    assert any("decision_error_rate" in item for item in assessment.hard_failures)


def test_report_must_be_isolated_to_requested_setup_family() -> None:
    mixed = report()
    mixed["setup_family_filter"] = None
    mixed["setup_families_observed"] = [SETUP, "sweep_reclaim"]
    with pytest.raises(ValueError, match="not isolated"):
        evidence_from_research_report(
            mixed,
            [decision(index) for index in range(10)],
            setup_family=SETUP,
            dataset_id=DATASET,
        )


def test_bundle_digest_is_order_independent_for_ablations() -> None:
    forward = build_evidence(
        ablation_rows=ablations(),
        replay_evidence=replay("same", "same"),
    )
    reverse = build_evidence(
        ablation_rows=tuple(reversed(ablations())),
        replay_evidence=replay("same", "same"),
    )
    assert forward.bundle_digest == reverse.bundle_digest
