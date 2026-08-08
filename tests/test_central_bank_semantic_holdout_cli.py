from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime, timedelta

import pytest

from scripts.create_central_bank_semantic_holdout import create_semantic_holdout_files
from scripts.finalize_central_bank_semantic_partition import finalize_semantic_partition_files
from forex_trader.infrastructure.official_document_repository import OfficialDocumentRepository
from forex_trader.intelligence.official_documents import OfficialDocumentVersion
from forex_trader.research.central_bank_stance import EvidenceDisposition, StanceDirection
from forex_trader.research.stance_annotation_workflow import (
    AdjudicationRecord,
    ReviewerSubmission,
    adjudication_to_dict,
    annotation_batch_to_dict,
    build_blinded_annotation_batch,
    load_annotation_batch,
    reviewer_submission_to_dict,
)
from forex_trader.research.stance_semantic_holdout import (
    SemanticPartition,
    load_semantic_holdout_manifest,
)
from forex_trader.research.stance_semantic_validation import load_semantic_label_corpus


BASE = datetime(2026, 8, 8, 12, 0, tzinfo=UTC)
FAMILY = "fed_fomc_holdout_cli"
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
        discovery_id=hashlib.sha256(f"holdout-cli-discovery-{suffix}".encode()).hexdigest(),
        item_id=f"holdout-cli-item-{suffix}",
        document_url=f"https://www.federalreserve.gov/holdout-cli-{suffix}.htm",
        published_at=available_at - timedelta(seconds=1),
        available_at=available_at,
        source_record_id=hashlib.sha256(f"holdout-cli-record-{suffix}".encode()).hexdigest(),
        source_payload_sha256=hashlib.sha256(f"holdout-cli-payload-{suffix}".encode()).hexdigest(),
        text_sha256=hashlib.sha256(text.encode()).hexdigest(),
        text=text,
        predecessor_version_id=predecessor_version_id,
    )


def setup_database(tmp_path):  # type: ignore[no-untyped-def]
    database = tmp_path / "documents.db"
    repository = OfficialDocumentRepository(database)
    texts = (
        "The Committee met today.",
        "The Committee met today.\nInflation remains elevated.",
        "The Committee met today.\nInflation has eased.",
        "The Committee met today.\nGrowth has slowed.",
        "The Committee met today.\nLabor demand remains strong.",
        "The Committee met today.\nPolicy remains restrictive.",
        "The Committee met today.\nPolicy may become less restrictive.",
    )
    versions: list[OfficialDocumentVersion] = []
    predecessor: str | None = None
    for index, text in enumerate(texts):
        item = version(
            index=index,
            text=text,
            available_at=BASE + timedelta(days=index),
            predecessor_version_id=predecessor,
        )
        repository.append(item)
        versions.append(item)
        predecessor = item.version_id
    batch = build_blinded_annotation_batch(
        versions,
        annotation_policy_version=POLICY,
        as_of=BASE + timedelta(days=7),
    )
    batch_path = tmp_path / "source-batch.json"
    batch_path.write_text(json.dumps(annotation_batch_to_dict(batch), sort_keys=True), encoding="utf-8")
    return database, tuple(versions), batch, batch_path


def write_jsonl(path, records):  # type: ignore[no-untyped-def]
    path.write_text("\n".join(json.dumps(item, sort_keys=True) for item in records) + "\n", encoding="utf-8")


def write_partition_evidence(tmp_path, partition_batch):  # type: ignore[no-untyped-def]
    submissions: list[ReviewerSubmission] = []
    adjudications: list[AdjudicationRecord] = []
    for index, packet in enumerate(partition_batch.packets):
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
    submissions_path = tmp_path / "submissions.jsonl"
    adjudications_path = tmp_path / "adjudications.jsonl"
    write_jsonl(submissions_path, [reviewer_submission_to_dict(item) for item in submissions])
    write_jsonl(adjudications_path, [adjudication_to_dict(item) for item in adjudications])
    return submissions_path, adjudications_path


def test_create_holdout_files_emit_manifest_and_two_normal_annotation_batches(tmp_path) -> None:
    _, _, source_batch, batch_path = setup_database(tmp_path)
    manifest_payload, calibration_payload, holdout_payload = create_semantic_holdout_files(batch_path)
    manifest_path = tmp_path / "manifest.json"
    calibration_path = tmp_path / "calibration.json"
    holdout_path = tmp_path / "holdout.json"
    manifest_path.write_text(json.dumps(manifest_payload), encoding="utf-8")
    calibration_path.write_text(json.dumps(calibration_payload), encoding="utf-8")
    holdout_path.write_text(json.dumps(holdout_payload), encoding="utf-8")

    manifest = load_semantic_holdout_manifest(manifest_path)
    calibration = load_annotation_batch(calibration_path)
    holdout = load_annotation_batch(holdout_path)
    assert manifest.source_batch_id == source_batch.manifest.batch_id
    assert calibration.manifest.packet_ids == manifest.calibration_packet_ids
    assert holdout.manifest.packet_ids == manifest.holdout_packet_ids
    assert manifest.calibration_packet_count == 4
    assert manifest.holdout_packet_count == 2


def test_partition_file_finalizer_produces_semantic_labels_and_partition_audit(tmp_path) -> None:
    database, _, _, batch_path = setup_database(tmp_path)
    manifest_payload, calibration_payload, _ = create_semantic_holdout_files(batch_path)
    manifest_path = tmp_path / "manifest.json"
    calibration_path = tmp_path / "calibration.json"
    manifest_path.write_text(json.dumps(manifest_payload), encoding="utf-8")
    calibration_path.write_text(json.dumps(calibration_payload), encoding="utf-8")
    calibration = load_annotation_batch(calibration_path)
    submissions_path, adjudications_path = write_partition_evidence(tmp_path, calibration)

    finalized = finalize_semantic_partition_files(
        database,
        batch_path,
        manifest_path,
        calibration_path,
        submissions_path,
        adjudications_path,
        partition=SemanticPartition.CALIBRATION,
    )
    assert len(finalized) == 4
    assert all(item.audit.partition is SemanticPartition.CALIBRATION for item in finalized)
    assert all(item.audit.reviewer_overall_agreement is False for item in finalized)

    labels_path = tmp_path / "labels.jsonl"
    write_jsonl(
        labels_path,
        [
            {
                "label_id": item.semantic_label.label_id,
                "schema_version": item.semantic_label.schema_version,
                "research_only": item.semantic_label.research_only,
                "execution_authority": item.semantic_label.execution_authority,
                "source": item.semantic_label.source,
                "diff_id": item.semantic_label.diff_id,
                "family_id": item.semantic_label.family_id,
                "previous_version_id": item.semantic_label.previous_version_id,
                "current_version_id": item.semantic_label.current_version_id,
                "annotation_policy_version": item.semantic_label.annotation_policy_version,
                "annotator_ids": list(item.semantic_label.annotator_ids),
                "adjudicated": item.semantic_label.adjudicated,
                "adjudicator_id": item.semantic_label.adjudicator_id,
                "labeled_at": item.semantic_label.labeled_at.isoformat(),
                "direction": item.semantic_label.direction.value,
                "disposition": item.semantic_label.disposition.value,
                "dimensions": [],
            }
            for item in finalized
        ],
    )
    assert len(load_semantic_label_corpus(labels_path)) == 4


def test_partition_file_finalizer_rejects_partition_batch_swap(tmp_path) -> None:
    database, _, _, batch_path = setup_database(tmp_path)
    manifest_payload, calibration_payload, holdout_payload = create_semantic_holdout_files(batch_path)
    manifest_path = tmp_path / "manifest.json"
    calibration_path = tmp_path / "calibration.json"
    holdout_path = tmp_path / "holdout.json"
    manifest_path.write_text(json.dumps(manifest_payload), encoding="utf-8")
    calibration_path.write_text(json.dumps(calibration_payload), encoding="utf-8")
    holdout_path.write_text(json.dumps(holdout_payload), encoding="utf-8")
    calibration = load_annotation_batch(calibration_path)
    submissions_path, adjudications_path = write_partition_evidence(tmp_path, calibration)

    with pytest.raises(ValueError, match="partition annotation batch"):
        finalize_semantic_partition_files(
            database,
            batch_path,
            manifest_path,
            holdout_path,
            submissions_path,
            adjudications_path,
            partition=SemanticPartition.CALIBRATION,
        )
