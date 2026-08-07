from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

import pytest

from forex_trader.research.ablations import (
    AblationVariant,
    FrozenAblationSnapshot,
    MaturedAblationOutcome,
    ProspectiveAblationCollector,
    ProspectiveAblationDecision,
    load_matured_ablation_outcomes,
    paired_ablation_evidence,
    paired_artifact_id,
    write_paired_ablation_evidence,
)

NOW = datetime(2026, 8, 7, 14, 0, tzinfo=UTC)
PAYLOAD_HASH = "a" * 64
POLICY = "policy-v1"
PRIMARY_DATASET = "b" * 64


def snapshot() -> FrozenAblationSnapshot:
    return FrozenAblationSnapshot(
        snapshot_id="snap-1",
        instrument="EUR_USD",
        signal_time=NOW,
        policy_fingerprint=POLICY,
        payload_hash=PAYLOAD_HASH,
    )


def decision(snap: FrozenAblationSnapshot, variant: AblationVariant, *, tradeable: bool = True) -> ProspectiveAblationDecision:
    return ProspectiveAblationDecision(
        snapshot_id=snap.snapshot_id,
        snapshot_payload_hash=snap.payload_hash,
        policy_fingerprint=snap.policy_fingerprint,
        instrument=snap.instrument,
        signal_time=snap.signal_time,
        variant=variant,
        tradeable=tradeable,
        setup_family="zone_continuation" if tradeable else None,
        direction="long" if tradeable else None,
        score=Decimal("0.8") if tradeable else None,
        entry_price=Decimal("1.1000") if tradeable else None,
        stop_loss=Decimal("1.0990") if tradeable else None,
        take_profit=Decimal("1.1030") if tradeable else None,
        rejection_code=None if tradeable else "abstain",
    )


def test_collector_runs_every_variant_on_the_exact_same_snapshot() -> None:
    seen: list[tuple[str, str, AblationVariant]] = []

    def evaluator(snap: FrozenAblationSnapshot, variant: AblationVariant) -> ProspectiveAblationDecision:
        seen.append((snap.snapshot_id, snap.payload_hash, variant))
        return decision(snap, variant)

    rows = ProspectiveAblationCollector(evaluator).collect(snapshot())
    assert tuple(row.variant for row in rows) == tuple(AblationVariant)
    assert len({row.snapshot_id for row in rows}) == 1
    assert len({row.snapshot_payload_hash for row in rows}) == 1
    assert len(seen) == len(tuple(AblationVariant))


def test_collector_retains_evaluator_failure_in_paired_denominator() -> None:
    def evaluator(snap: FrozenAblationSnapshot, variant: AblationVariant) -> ProspectiveAblationDecision:
        if variant is AblationVariant.NO_FLOW:
            raise RuntimeError("flow provider unavailable")
        return decision(snap, variant)

    rows = ProspectiveAblationCollector(evaluator).collect(snapshot())
    failed = next(row for row in rows if row.variant is AblationVariant.NO_FLOW)
    assert failed.tradeable is False
    assert failed.rejection_code == "evaluation_error"
    assert failed.error_type == "RuntimeError"
    assert "flow provider unavailable" in (failed.error_message or "")


def test_collector_rejects_evaluator_that_changes_snapshot_identity() -> None:
    def evaluator(snap: FrozenAblationSnapshot, variant: AblationVariant) -> ProspectiveAblationDecision:
        row = decision(snap, variant)
        return ProspectiveAblationDecision(
            snapshot_id="different-snapshot",
            snapshot_payload_hash=row.snapshot_payload_hash,
            policy_fingerprint=row.policy_fingerprint,
            instrument=row.instrument,
            signal_time=row.signal_time,
            variant=row.variant,
            tradeable=row.tradeable,
            setup_family=row.setup_family,
            direction=row.direction,
            score=row.score,
            entry_price=row.entry_price,
            stop_loss=row.stop_loss,
            take_profit=row.take_profit,
            rejection_code=row.rejection_code,
        )

    with pytest.raises(ValueError, match="changed snapshot_id"):
        ProspectiveAblationCollector(evaluator).collect(snapshot())


def outcome(snapshot_id: str, variant: AblationVariant, realized_r: str) -> MaturedAblationOutcome:
    return MaturedAblationOutcome(
        snapshot_id=snapshot_id,
        snapshot_payload_hash=PAYLOAD_HASH,
        policy_fingerprint=POLICY,
        variant=variant,
        realized_r=Decimal(realized_r),
        status="win" if Decimal(realized_r) > 0 else "loss",
    )


def complete_outcomes() -> tuple[MaturedAblationOutcome, ...]:
    rows: list[MaturedAblationOutcome] = []
    for snapshot_id, full_r in (("a", "1"), ("b", "-1")):
        for variant in AblationVariant:
            if variant is AblationVariant.FULL:
                value = full_r
            elif variant is AblationVariant.NO_FUNDAMENTALS:
                value = "-1"
            else:
                value = full_r
            rows.append(outcome(snapshot_id, variant, value))
    return tuple(rows)


def test_paired_evidence_uses_same_snapshot_denominator_and_primary_dataset_identity() -> None:
    evidence = paired_ablation_evidence(complete_outcomes(), primary_dataset_id=PRIMARY_DATASET)
    by_name = {item.name: item for item in evidence}
    no_fundamentals = by_name["no_fundamentals"]
    assert no_fundamentals.sample_size == 2
    assert no_fundamentals.dataset_id == PRIMARY_DATASET
    assert no_fundamentals.full_expectancy_r == Decimal("0")
    assert no_fundamentals.ablated_expectancy_r == Decimal("-1")
    assert no_fundamentals.component_increment_r == Decimal("1")


def test_missing_variant_for_one_snapshot_fails_closed() -> None:
    rows = list(complete_outcomes())
    rows = [row for row in rows if not (row.snapshot_id == "b" and row.variant is AblationVariant.NO_RETEST)]
    with pytest.raises(ValueError, match="missing paired variants"):
        paired_ablation_evidence(rows, primary_dataset_id=PRIMARY_DATASET)


def test_duplicate_variant_for_snapshot_fails_closed() -> None:
    rows = list(complete_outcomes())
    rows.append(outcome("a", AblationVariant.NO_FLOW, "0"))
    with pytest.raises(ValueError, match="duplicate matured outcome"):
        paired_ablation_evidence(rows, primary_dataset_id=PRIMARY_DATASET)


def test_writer_emits_promotion_compatible_ablation_schema(tmp_path) -> None:
    rows = complete_outcomes()
    evidence = paired_ablation_evidence(rows, primary_dataset_id=PRIMARY_DATASET)
    artifact_id = paired_artifact_id(rows)
    path = tmp_path / "ablations.json"
    write_paired_ablation_evidence(path, evidence, artifact_id=artifact_id)
    text = path.read_text(encoding="utf-8")
    assert f'"dataset_id": "{PRIMARY_DATASET}"' in text
    assert f'"paired_artifact_id": "{artifact_id}"' in text
    assert '"name": "no_fundamentals"' in text
    assert '"sample_size": 2' in text


def test_matured_outcome_loader_rejects_invalid_jsonl(tmp_path) -> None:
    path = tmp_path / "bad.jsonl"
    path.write_text('{"snapshot_id":"a"}\n', encoding="utf-8")
    with pytest.raises(ValueError, match="invalid matured ablation JSONL"):
        load_matured_ablation_outcomes(path)
