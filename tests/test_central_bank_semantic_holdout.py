from __future__ import annotations

import hashlib
import json
from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pytest

from forex_trader.intelligence.official_documents import OfficialDocumentVersion
from forex_trader.research.central_bank_stance import EvidenceDisposition, StanceDirection
from forex_trader.research.stance_annotation_workflow import (
    AdjudicationRecord,
    AnnotationBatch,
    ReviewerSubmission,
    annotation_batch_to_dict,
    build_blinded_annotation_batch,
    finalize_annotation_batch,
)
from forex_trader.research.stance_semantic_holdout import (
    SEMANTIC_HOLDOUT_SPLIT_DENOMINATOR,
    SEMANTIC_HOLDOUT_SPLIT_NUMERATOR,
    SemanticPartition,
    build_partition_annotation_batch,
    build_semantic_holdout_manifest,
    finalize_semantic_partition,
    load_semantic_holdout_manifest,
    semantic_holdout_manifest_to_dict,
)


BASE = datetime(2026, 8, 8, 12, 0, tzinfo=UTC)
FAMILY = "fed_fomc_holdout_fixture"
POLICY = "central-bank-human-annotation-v1"


def version(
    *,
    index: int,
    text: str,
    available_at: datetime,
    predecessor_version_id: str | None,
) -> OfficialDocumentVersion:
    suffix = str(index)
    return OfficialDocumentVersion(
        family_id=FAMILY,
        source_id="federal_reserve",
        document_type="monetary_policy_statement",
        institution="Federal Reserve",
        currency="USD",
        discovery_id=hashlib.sha256(f"holdout-discovery-{suffix}".encode()).hexdigest(),
        item_id=f"holdout-item-{suffix}",
        document_url=f"https://www.federalreserve.gov/holdout-{suffix}.htm",
        published_at=available_at - timedelta(seconds=1),
        available_at=available_at,
        source_record_id=hashlib.sha256(f"holdout-record-{suffix}".encode()).hexdigest(),
        source_payload_sha256=hashlib.sha256(f"holdout-payload-{suffix}".encode()).hexdigest(),
        text_sha256=hashlib.sha256(text.encode()).hexdigest(),
        text=text,
        predecessor_version_id=predecessor_version_id,
    )


def source_versions() -> tuple[OfficialDocumentVersion, ...]:
    texts = (
        "The Committee met today.",
        "The Committee met today.\nInflation remains elevated.",
        "The Committee met today.\nInflation has eased.",
        "The Committee met today.\nGrowth has slowed.",
        "The Committee met today.\nLabor demand remains strong.",
        "The Committee met today.\nPolicy remains restrictive.",
        "The Committee met today.\nPolicy may become less restrictive.",
    )
    result: list[OfficialDocumentVersion] = []
    predecessor: str | None = None
    for index, text in enumerate(texts):
        item = version(
            index=index,
            text=text,
            available_at=BASE + timedelta(days=index),
            predecessor_version_id=predecessor,
        )
        result.append(item)
        predecessor = item.version_id
    return tuple(result)


def frozen_source_batch() -> tuple[tuple[OfficialDocumentVersion, ...], AnnotationBatch]:
    versions = source_versions()
    batch = build_blinded_annotation_batch(
        reversed(versions),
        annotation_policy_version=POLICY,
        as_of=BASE + timedelta(days=7),
    )
    return versions, batch


def review(
    packet,  # type: ignore[no-untyped-def]
    reviewer_id: str,
    *,
    offset_minutes: int,
    direction: StanceDirection = StanceDirection.HAWKISH,
) -> ReviewerSubmission:
    return ReviewerSubmission.create(
        packet,
        reviewer_id=reviewer_id,
        submitted_at=BASE + timedelta(days=20, minutes=offset_minutes),
        direction=direction,
        disposition=EvidenceDisposition.SUPPORTED,
    )


def evidence_for(batch: AnnotationBatch) -> tuple[tuple[ReviewerSubmission, ...], tuple[AdjudicationRecord, ...]]:
    submissions: list[ReviewerSubmission] = []
    adjudications: list[AdjudicationRecord] = []
    for index, packet in enumerate(batch.packets):
        first = review(packet, f"reviewer-a-{index}", offset_minutes=index * 2 + 1)
        second = review(packet, f"reviewer-b-{index}", offset_minutes=index * 2 + 2)
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


def test_manifest_is_deterministic_chronological_and_complete() -> None:
    _, batch = frozen_source_batch()
    manifest = build_semantic_holdout_manifest(batch)
    assert manifest.source_packet_count == 6
    assert manifest.split_numerator == SEMANTIC_HOLDOUT_SPLIT_NUMERATOR == 2
    assert manifest.split_denominator == SEMANTIC_HOLDOUT_SPLIT_DENOMINATOR == 3
    assert manifest.calibration_packet_count == 4
    assert manifest.holdout_packet_count == 2
    assert manifest.calibration_packet_ids == batch.manifest.packet_ids[:4]
    assert manifest.holdout_packet_ids == batch.manifest.packet_ids[4:]
    assert set(manifest.calibration_packet_ids).isdisjoint(manifest.holdout_packet_ids)
    assert manifest.calibration_packet_ids + manifest.holdout_packet_ids == batch.manifest.packet_ids
    assert build_semantic_holdout_manifest(batch) == manifest


def test_manifest_identity_detects_tampering_and_requires_minimum_sample() -> None:
    _, batch = frozen_source_batch()
    manifest = build_semantic_holdout_manifest(batch)
    with pytest.raises(ValueError, match="manifest ID"):
        replace(manifest, annotation_policy_version="tampered-policy")

    versions = source_versions()[:3]
    two_packet_batch = build_blinded_annotation_batch(
        versions,
        annotation_policy_version=POLICY,
        as_of=BASE + timedelta(days=3),
    )
    with pytest.raises(ValueError, match="at least three"):
        build_semantic_holdout_manifest(two_packet_batch)


def test_partition_batches_are_existing_annotation_batches_with_no_overlap() -> None:
    _, batch = frozen_source_batch()
    manifest = build_semantic_holdout_manifest(batch)
    calibration = build_partition_annotation_batch(batch, manifest, SemanticPartition.CALIBRATION)
    holdout = build_partition_annotation_batch(batch, manifest, SemanticPartition.HOLDOUT)
    assert calibration.manifest.packet_ids == manifest.calibration_packet_ids
    assert holdout.manifest.packet_ids == manifest.holdout_packet_ids
    assert calibration.manifest.batch_id != holdout.manifest.batch_id
    assert calibration.manifest.batch_id != batch.manifest.batch_id
    assert holdout.manifest.batch_id != batch.manifest.batch_id
    assert {item.packet_id for item in calibration.packets}.isdisjoint(item.packet_id for item in holdout.packets)
    assert annotation_batch_to_dict(calibration)["manifest"]
    assert annotation_batch_to_dict(holdout)["manifest"]


def test_original_full_batch_finalizer_still_fails_closed_on_calibration_only_evidence() -> None:
    versions, batch = frozen_source_batch()
    manifest = build_semantic_holdout_manifest(batch)
    calibration = build_partition_annotation_batch(batch, manifest, SemanticPartition.CALIBRATION)
    submissions, adjudications = evidence_for(calibration)
    with pytest.raises(ValueError, match="every annotation packet requires"):
        finalize_annotation_batch(batch, submissions, adjudications, versions)


def test_calibration_partition_finalizes_independently_with_generator_source_verification() -> None:
    versions, batch = frozen_source_batch()
    manifest = build_semantic_holdout_manifest(batch)
    calibration = build_partition_annotation_batch(batch, manifest, SemanticPartition.CALIBRATION)
    submissions, adjudications = evidence_for(calibration)
    finalized = finalize_semantic_partition(
        batch,
        manifest,
        calibration,
        SemanticPartition.CALIBRATION,
        submissions,
        adjudications,
        (item for item in versions),
    )
    assert len(finalized) == manifest.calibration_packet_count
    assert all(item.audit.partition is SemanticPartition.CALIBRATION for item in finalized)
    assert all(item.audit.holdout_manifest_id == manifest.manifest_id for item in finalized)
    assert all(item.audit.source_batch_id == batch.manifest.batch_id for item in finalized)
    assert all(item.audit.partition_batch_id == calibration.manifest.batch_id for item in finalized)
    assert all(item.semantic_label.adjudicated for item in finalized)


def test_holdout_partition_can_finalize_without_calibration_labels() -> None:
    versions, batch = frozen_source_batch()
    manifest = build_semantic_holdout_manifest(batch)
    holdout = build_partition_annotation_batch(batch, manifest, SemanticPartition.HOLDOUT)
    submissions, adjudications = evidence_for(holdout)
    finalized = finalize_semantic_partition(
        batch,
        manifest,
        holdout,
        SemanticPartition.HOLDOUT,
        submissions,
        adjudications,
        versions,
    )
    assert len(finalized) == manifest.holdout_packet_count
    assert all(item.audit.partition is SemanticPartition.HOLDOUT for item in finalized)
    assert tuple(item.audit.packet_id for item in finalized) == manifest.holdout_packet_ids


def test_cross_partition_submission_and_wrong_partition_batch_fail_closed() -> None:
    versions, batch = frozen_source_batch()
    manifest = build_semantic_holdout_manifest(batch)
    calibration = build_partition_annotation_batch(batch, manifest, SemanticPartition.CALIBRATION)
    holdout = build_partition_annotation_batch(batch, manifest, SemanticPartition.HOLDOUT)
    submissions, adjudications = evidence_for(calibration)
    foreign = review(holdout.packets[0], "holdout-reviewer", offset_minutes=99)
    with pytest.raises(ValueError, match="crosses the sealed semantic partition boundary"):
        finalize_semantic_partition(
            batch,
            manifest,
            calibration,
            SemanticPartition.CALIBRATION,
            submissions + (foreign,),
            adjudications,
            versions,
        )
    with pytest.raises(ValueError, match="partition annotation batch"):
        finalize_semantic_partition(
            batch,
            manifest,
            holdout,
            SemanticPartition.CALIBRATION,
            submissions,
            adjudications,
            versions,
        )


def test_partition_finalization_rejects_incomplete_and_cherry_picked_adjudication() -> None:
    versions, batch = frozen_source_batch()
    manifest = build_semantic_holdout_manifest(batch)
    calibration = build_partition_annotation_batch(batch, manifest, SemanticPartition.CALIBRATION)
    submissions, adjudications = evidence_for(calibration)
    with pytest.raises(ValueError, match="exactly one adjudication"):
        finalize_semantic_partition(
            batch,
            manifest,
            calibration,
            SemanticPartition.CALIBRATION,
            submissions,
            adjudications[:-1],
            versions,
        )

    packet = calibration.packets[0]
    packet_reviews = tuple(item for item in submissions if item.packet_id == packet.packet_id)
    extra = review(packet, "reviewer-extra", offset_minutes=88)
    cherry_picked = AdjudicationRecord.create(
        packet,
        packet_reviews,
        adjudicator_id="adjudicator-extra",
        adjudicated_at=BASE + timedelta(days=22),
        direction=StanceDirection.HAWKISH,
        disposition=EvidenceDisposition.SUPPORTED,
    )
    other_adjudications = tuple(item for item in adjudications if item.packet_id != packet.packet_id)
    with pytest.raises(ValueError, match="account for every reviewer submission"):
        finalize_semantic_partition(
            batch,
            manifest,
            calibration,
            SemanticPartition.CALIBRATION,
            submissions + (extra,),
            (cherry_picked,) + other_adjudications,
            versions,
        )


def test_manifest_loader_round_trips_and_rejects_hidden_fields(tmp_path) -> None:
    _, batch = frozen_source_batch()
    manifest = build_semantic_holdout_manifest(batch)
    payload = semantic_holdout_manifest_to_dict(manifest)
    path = tmp_path / "holdout-manifest.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    assert load_semantic_holdout_manifest(path) == manifest

    payload["model_prediction"] = "hawkish"
    path.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(ValueError, match="unexpected=.*model_prediction"):
        load_semantic_holdout_manifest(path)


def test_partition_finalization_rejects_source_corpus_drift() -> None:
    versions, batch = frozen_source_batch()
    manifest = build_semantic_holdout_manifest(batch)
    calibration = build_partition_annotation_batch(batch, manifest, SemanticPartition.CALIBRATION)
    submissions, adjudications = evidence_for(calibration)
    with pytest.raises(ValueError):
        finalize_semantic_partition(
            batch,
            manifest,
            calibration,
            SemanticPartition.CALIBRATION,
            submissions,
            adjudications,
            versions[:-1],
        )
