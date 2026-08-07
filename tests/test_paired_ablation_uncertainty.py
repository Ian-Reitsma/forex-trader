from __future__ import annotations

import json
from decimal import Decimal
from pathlib import Path

import pytest

from forex_trader.research.ablation_uncertainty import (
    paired_ablation_uncertainty_evidence,
    write_paired_ablation_uncertainty_evidence,
)
from forex_trader.research.ablations import AblationVariant, MaturedAblationOutcome, paired_artifact_id


DATASET = "d" * 64
PAYLOAD = "a" * 64
POLICY = "policy-v0.7.9"


def _outcomes(samples: int = 20) -> tuple[MaturedAblationOutcome, ...]:
    rows: list[MaturedAblationOutcome] = []
    for index in range(samples):
        full_r = Decimal("0.30") if index % 2 == 0 else Decimal("-0.10")
        for variant in AblationVariant:
            if variant is AblationVariant.FULL:
                realized = full_r
            elif variant is AblationVariant.NO_FUNDAMENTALS:
                realized = full_r - Decimal("0.10")
            elif variant is AblationVariant.NO_FLOW:
                realized = full_r + (Decimal("0.04") if index % 2 == 0 else Decimal("-0.04"))
            elif variant is AblationVariant.NO_SESSION:
                realized = full_r
            elif variant is AblationVariant.NO_ZONE_QUALITY:
                realized = full_r - Decimal("0.02")
            else:
                realized = full_r - (Decimal("0.06") if index % 3 else Decimal("-0.02"))
            rows.append(
                MaturedAblationOutcome(
                    snapshot_id=f"snap-{index:03d}",
                    snapshot_payload_hash=PAYLOAD,
                    policy_fingerprint=POLICY,
                    variant=variant,
                    realized_r=realized,
                    status="timeout",
                )
            )
    return tuple(rows)


def test_paired_uncertainty_is_deterministic_and_uses_full_minus_ablated_delta() -> None:
    outcomes = _outcomes()
    first = paired_ablation_uncertainty_evidence(
        outcomes,
        primary_dataset_id=DATASET,
        confidence=Decimal("0.90"),
        bootstrap_iterations=1000,
        bootstrap_seed=17,
    )
    second = paired_ablation_uncertainty_evidence(
        outcomes,
        primary_dataset_id=DATASET,
        confidence=Decimal("0.90"),
        bootstrap_iterations=1000,
        bootstrap_seed=17,
    )
    assert first == second
    by_name = {item.name: item for item in first}
    fundamentals = by_name[AblationVariant.NO_FUNDAMENTALS.value]
    assert fundamentals.component_increment_r == Decimal("0.10")
    assert fundamentals.lower_confidence_component_increment_r == Decimal("0.10")
    assert fundamentals.upper_confidence_component_increment_r == Decimal("0.10")
    assert (fundamentals.paired_wins, fundamentals.paired_losses, fundamentals.paired_ties) == (20, 0, 0)

    flow = by_name[AblationVariant.NO_FLOW.value]
    assert flow.component_increment_r == Decimal("0.00")
    assert (flow.paired_wins, flow.paired_losses, flow.paired_ties) == (10, 10, 0)

    session = by_name[AblationVariant.NO_SESSION.value]
    assert session.component_increment_r == Decimal("0.00")
    assert (session.paired_wins, session.paired_losses, session.paired_ties) == (0, 0, 20)


def test_uncertainty_artifact_serializes_method_configuration_and_counts(tmp_path) -> None:
    outcomes = _outcomes()
    evidence = paired_ablation_uncertainty_evidence(
        outcomes,
        primary_dataset_id=DATASET,
        confidence=Decimal("0.95"),
        bootstrap_iterations=1200,
        bootstrap_seed=42,
    )
    output = tmp_path / "ablations.json"
    write_paired_ablation_uncertainty_evidence(
        output,
        evidence,
        artifact_id=paired_artifact_id(outcomes),
    )
    payload = json.loads(output.read_text(encoding="utf-8"))
    assert payload["research_only"] is True
    assert payload["execution_authority"] is False
    assert payload["uncertainty"] == {
        "method": "paired_bootstrap_mean_percentile",
        "delta_semantics": "full_realized_r_minus_ablated_realized_r",
        "confidence": "0.95",
        "bootstrap_iterations": 1200,
        "bootstrap_seed": 42,
    }
    assert len(payload["ablations"]) == 5
    row = next(item for item in payload["ablations"] if item["name"] == "no_fundamentals")
    assert row["component_increment_r"] == "0.10"
    assert row["paired_wins"] == 20
    assert row["lower_confidence_component_increment_r"] == "0.10"


def test_invalid_bootstrap_configuration_fails_closed() -> None:
    outcomes = _outcomes()
    with pytest.raises(ValueError, match="confidence"):
        paired_ablation_uncertainty_evidence(
            outcomes,
            primary_dataset_id=DATASET,
            confidence=Decimal("1"),
        )
    with pytest.raises(ValueError, match="iterations"):
        paired_ablation_uncertainty_evidence(
            outcomes,
            primary_dataset_id=DATASET,
            bootstrap_iterations=99,
        )


def test_assembler_exposes_deterministic_bootstrap_controls() -> None:
    text = Path("scripts/assemble_paired_ablations.py").read_text(encoding="utf-8")
    assert "--confidence" in text
    assert "--bootstrap-iterations" in text
    assert "--bootstrap-seed" in text
    assert "paired_ablation_uncertainty_evidence" in text
