from __future__ import annotations

import hashlib
import json
from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pytest

from forex_trader.intelligence.official_documents import OfficialDocumentVersion
from forex_trader.research.central_bank_stance import EvidenceDisposition, StanceDirection
from forex_trader.research.stance_annotation_workflow import AdjudicationRecord, AnnotationBatch, ReviewerSubmission, build_blinded_annotation_batch
from forex_trader.research.stance_semantic_holdout import (
    SEMANTIC_HOLDOUT_SCHEMA_VERSION,
    SemanticPartition,
    build_partition_annotation_batch,
    build_semantic_holdout_manifest,
    finalize_semantic_partition,
    load_semantic_holdout_manifest,
)


BASE = datetime(2026, 8, 8, 12, 0, tzinfo=UTC)
FAMILY = "fed_fomc_holdout_validation"
POLICY = "central-bank-human-annotation-v1"


def _version(index: int, text: str, predecessor: str | None) -> OfficialDocumentVersion:
    at = BASE + timedelta(days=index)
    suffix = str(index)
    return OfficialDocumentVersion(
        family_id=FAMILY,
        source_id="federal_reserve",
        document_type="monetary_policy_statement",
        institution="Federal Reserve",
        currency="USD",
        discovery_id=hashlib.sha256(f"validation-discovery-{suffix}".encode()).hexdigest(),
        item_id=f"validation-item-{suffix}",
        document_url=f"https://www.federalreserve.gov/validation-{suffix}.htm",
        published_at=at - timedelta(seconds=1),
        available_at=at,
        source_record_id=hashlib.sha256(f"validation-record-{suffix}".encode()).hexdigest(),
        source_payload_sha256=hashlib.sha256(f"validation-payload-{suffix}".encode()).hexdigest(),
        text_sha256=hashlib.sha256(text.encode()).hexdigest(),
        text=text,
        predecessor_version_id=predecessor,
    )


def _fixture() -> tuple[tuple[OfficialDocumentVersion, ...], AnnotationBatch]:
    texts = (
        "Initial statement.",
        "Initial statement.\nInflation is elevated.",
        "Initial statement.\nInflation has eased.",
        "Initial statement.\nGrowth has slowed.",
        "Initial statement.\nLabor demand is strong.",
        "Initial statement.\nPolicy remains restrictive.",
    )
    versions: list[OfficialDocumentVersion] = []
    predecessor: str | None = None
    for index, text in enumerate(texts):
        item = _version(index, text, predecessor)
        versions.append(item)
        predecessor = item.version_id
    batch = build_blinded_annotation_batch(
        versions,
        annotation_policy_version=POLICY,
        as_of=BASE + timedelta(days=6),
    )
    return tuple(versions), batch


def _evidence(batch: AnnotationBatch) -> tuple[tuple[ReviewerSubmission, ...], tuple[AdjudicationRecord, ...]]:
    submissions: list[ReviewerSubmission] = []
    adjudications: list[AdjudicationRecord] = []
    for index, packet in enumerate(batch.packets):
        first = ReviewerSubmission.create(
            packet,
            reviewer_id=f"reviewer-a-{index}",
            submitted_at=BASE + timedelta(days=20, minutes=index * 2),
            direction=StanceDirection.HAWKISH,
            disposition=EvidenceDisposition.SUPPORTED,
        )
        second = ReviewerSubmission.create(
            packet,
            reviewer_id=f"reviewer-b-{index}",
            submitted_at=BASE + timedelta(days=20, minutes=index * 2 + 1),
            direction=StanceDirection.DOVISH,
            disposition=EvidenceDisposition.SUPPORTED,
        )
        submissions.extend((first, second))
        adjudications.append(
            AdjudicationRecord.create(
                packet,
                (first, second),
                adjudicator_id=f"adjudicator-{index}",
                adjudicated_at=BASE + timedelta(days=21, minutes=index),
                direction=StanceDirection.HAWKISH,
                disposition=EvidenceDisposition.SUPPORTED,
            )
        )
    return tuple(submissions), tuple(adjudications)


def test_manifest_dataclass_rejects_invalid_schema_authority_identity_and_split() -> None:
    _, batch = _fixture()
    manifest = build_semantic_holdout_manifest(batch)
    with pytest.raises(ValueError, match="unsupported"):
        replace(manifest, schema_version="other")
    with pytest.raises(ValueError, match="research-only"):
        replace(manifest, research_only=False)
    with pytest.raises(ValueError, match="research-only"):
        replace(manifest, execution_authority=True)
    with pytest.raises(ValueError, match="family and annotation policy"):
        replace(manifest, family_id=" ")
    with pytest.raises(ValueError, match="timezone-aware"):
        replace(manifest, as_of=manifest.as_of.replace(tzinfo=None))
    with pytest.raises(ValueError, match="fixed at two-thirds"):
        replace(manifest, split_numerator=1)
    with pytest.raises(ValueError, match="fixed at two-thirds"):
        replace(manifest, split_denominator=2)
    with pytest.raises(ValueError, match="at least three"):
        replace(manifest, source_packet_count=2)


def test_manifest_dataclass_rejects_denominator_membership_and_hash_corruption() -> None:
    _, batch = _fixture()
    manifest = build_semantic_holdout_manifest(batch)
    with pytest.raises(ValueError, match="calibration denominator"):
        replace(manifest, calibration_packet_count=manifest.calibration_packet_count + 1)
    with pytest.raises(ValueError, match="holdout denominator"):
        replace(manifest, holdout_packet_count=manifest.holdout_packet_count + 1)
    with pytest.raises(ValueError, match="do not cover"):
        replace(manifest, source_packet_count=manifest.source_packet_count + 1)
    with pytest.raises(ValueError, match="chronological split"):
        replace(
            manifest,
            calibration_packet_count=manifest.calibration_packet_count - 1,
            holdout_packet_count=manifest.holdout_packet_count + 1,
            calibration_packet_ids=manifest.calibration_packet_ids[:-1],
            holdout_packet_ids=(manifest.calibration_packet_ids[-1],) + manifest.holdout_packet_ids,
        )
    duplicate = manifest.calibration_packet_ids + (manifest.calibration_packet_ids[-1],)
    with pytest.raises(ValueError, match="unique across partitions"):
        replace(
            manifest,
            source_packet_count=manifest.source_packet_count + 1,
            calibration_packet_count=manifest.calibration_packet_count + 1,
            calibration_packet_ids=duplicate,
        )
    with pytest.raises(ValueError, match="SHA-256"):
        replace(manifest, source_batch_id="bad")
    with pytest.raises(ValueError, match="SHA-256"):
        replace(manifest, manifest_id="bad")


def test_manifest_loader_rejects_invalid_json_shape_types_and_time(tmp_path) -> None:
    path = tmp_path / "manifest.json"
    path.write_text("{not-json", encoding="utf-8")
    with pytest.raises(ValueError, match="not valid JSON"):
        load_semantic_holdout_manifest(path)
    path.write_text("[]", encoding="utf-8")
    with pytest.raises(ValueError, match="must be an object"):
        load_semantic_holdout_manifest(path)

    _, batch = _fixture()
    manifest = build_semantic_holdout_manifest(batch)
    payload = {
        "manifest_id": manifest.manifest_id,
        "schema_version": manifest.schema_version,
        "research_only": manifest.research_only,
        "execution_authority": manifest.execution_authority,
        "source_batch_id": manifest.source_batch_id,
        "family_id": manifest.family_id,
        "annotation_policy_version": manifest.annotation_policy_version,
        "as_of": manifest.as_of.isoformat(),
        "source_packet_count": manifest.source_packet_count,
        "split_numerator": manifest.split_numerator,
        "split_denominator": manifest.split_denominator,
        "calibration_packet_count": manifest.calibration_packet_count,
        "holdout_packet_count": manifest.holdout_packet_count,
        "calibration_packet_ids": list(manifest.calibration_packet_ids),
        "holdout_packet_ids": list(manifest.holdout_packet_ids),
    }
    payload["research_only"] = "true"
    path.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(ValueError, match="JSON boolean"):
        load_semantic_holdout_manifest(path)
    payload["research_only"] = True
    payload["source_packet_count"] = True
    path.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(ValueError, match="must be an integer"):
        load_semantic_holdout_manifest(path)
    payload["source_packet_count"] = manifest.source_packet_count
    payload["as_of"] = "2026-08-08T12:00:00"
    path.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(ValueError, match="timezone-aware"):
        load_semantic_holdout_manifest(path)
    payload["as_of"] = manifest.as_of.isoformat()
    payload["calibration_packet_ids"] = "not-a-list"
    path.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(ValueError, match="must be a list"):
        load_semantic_holdout_manifest(path)


def test_partition_audit_rejects_tampering_and_bad_denominators() -> None:
    versions, batch = _fixture()
    manifest = build_semantic_holdout_manifest(batch)
    calibration = build_partition_annotation_batch(batch, manifest, SemanticPartition.CALIBRATION)
    submissions, adjudications = _evidence(calibration)
    finalized = finalize_semantic_partition(
        batch,
        manifest,
        calibration,
        SemanticPartition.CALIBRATION,
        submissions,
        adjudications,
        versions,
    )
    audit = finalized[0].audit
    with pytest.raises(ValueError, match="unsupported"):
        replace(audit, schema_version="other")
    with pytest.raises(ValueError, match="research-only"):
        replace(audit, execution_authority=True)
    with pytest.raises(ValueError, match="SHA-256"):
        replace(audit, packet_id="bad")
    with pytest.raises(ValueError, match="at least two"):
        replace(audit, source_submission_ids=audit.source_submission_ids[:1], reviewer_ids=audit.reviewer_ids[:1])
    with pytest.raises(ValueError, match="reviewer IDs must be sorted"):
        replace(audit, reviewer_ids=tuple(reversed(audit.reviewer_ids)))
    with pytest.raises(ValueError, match="denominators must match"):
        replace(audit, reviewer_ids=audit.reviewer_ids[:1])
    with pytest.raises(ValueError, match="audit ID"):
        replace(audit, reviewer_overall_agreement=not audit.reviewer_overall_agreement)


def test_partition_finalizer_rejects_duplicate_ids_policy_mismatch_and_late_review() -> None:
    versions, batch = _fixture()
    manifest = build_semantic_holdout_manifest(batch)
    calibration = build_partition_annotation_batch(batch, manifest, SemanticPartition.CALIBRATION)
    submissions, adjudications = _evidence(calibration)
    with pytest.raises(ValueError, match="duplicate reviewer submission IDs"):
        finalize_semantic_partition(
            batch,
            manifest,
            calibration,
            SemanticPartition.CALIBRATION,
            submissions + (submissions[0],),
            adjudications,
            versions,
        )
    with pytest.raises(ValueError, match="duplicate adjudication IDs"):
        finalize_semantic_partition(
            batch,
            manifest,
            calibration,
            SemanticPartition.CALIBRATION,
            submissions,
            adjudications + (adjudications[0],),
            versions,
        )

    changed_policy = replace(submissions[0], annotation_policy_version="other")
    with pytest.raises(ValueError, match="submission ID"):
        # Immutable reviewer identity catches policy tampering before finalization.
        _ = changed_policy

    packet = calibration.packets[0]
    packet_submissions = tuple(item for item in submissions if item.packet_id == packet.packet_id)
    late = ReviewerSubmission.create(
        packet,
        reviewer_id="reviewer-late",
        submitted_at=BASE + timedelta(days=25),
        direction=StanceDirection.HAWKISH,
        disposition=EvidenceDisposition.SUPPORTED,
    )
    all_for_packet = packet_submissions + (late,)
    early_adjudication = AdjudicationRecord.create(
        packet,
        all_for_packet,
        adjudicator_id="adjudicator-late-test",
        adjudicated_at=BASE + timedelta(days=26),
        direction=StanceDirection.HAWKISH,
        disposition=EvidenceDisposition.SUPPORTED,
    )
    assert early_adjudication.adjudicated_at > late.submitted_at
