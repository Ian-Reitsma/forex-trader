from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime, timedelta

import pytest

from scripts.export_central_bank_annotation_batch import _parse_as_of, export_annotation_batch
from scripts.finalize_central_bank_annotations import finalize_annotation_files
from forex_trader.infrastructure.official_document_repository import OfficialDocumentRepository
from forex_trader.intelligence.official_documents import OfficialDocumentVersion
from forex_trader.research.central_bank_stance import EvidenceDisposition, StanceDirection
from forex_trader.research.stance_annotation_workflow import (
    AdjudicationRecord,
    ReviewerSubmission,
    adjudication_to_dict,
    annotation_batch_to_dict,
    finalization_audit_to_dict,
    load_annotation_batch,
    reviewer_submission_to_dict,
    semantic_label_to_dict,
)
from forex_trader.research.stance_semantic_validation import load_semantic_label_corpus


BASE = datetime(2026, 8, 8, 12, 0, tzinfo=UTC)
FAMILY = "fed_fomc_annotation_cli"
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
        discovery_id=hashlib.sha256(f"discovery-{suffix}".encode()).hexdigest(),
        item_id=f"item-{suffix}",
        document_url=f"https://www.federalreserve.gov/annotation-cli-{suffix}.htm",
        published_at=available_at - timedelta(seconds=1),
        available_at=available_at,
        source_record_id=hashlib.sha256(f"record-{suffix}".encode()).hexdigest(),
        source_payload_sha256=hashlib.sha256(f"payload-{suffix}".encode()).hexdigest(),
        text_sha256=hashlib.sha256(text.encode()).hexdigest(),
        text=text,
        predecessor_version_id=predecessor_version_id,
    )


def setup_database(tmp_path):  # type: ignore[no-untyped-def]
    database = tmp_path / "documents.db"
    repository = OfficialDocumentRepository(database)
    first = version(
        index=0,
        text="The Committee met today.",
        available_at=BASE,
        predecessor_version_id=None,
    )
    second = version(
        index=1,
        text="The Committee met today.\nInflation remains elevated.",
        available_at=BASE + timedelta(days=1),
        predecessor_version_id=first.version_id,
    )
    repository.append(first)
    repository.append(second)
    return database, (first, second)


def write_jsonl(path, records):  # type: ignore[no-untyped-def]
    path.write_text("\n".join(json.dumps(item, sort_keys=True) for item in records) + "\n", encoding="utf-8")


def test_export_and_finalize_files_produce_v017_labels_and_separate_audit(tmp_path) -> None:
    database, versions = setup_database(tmp_path)
    batch = export_annotation_batch(
        database,
        family_id=FAMILY,
        annotation_policy_version=POLICY,
        as_of=BASE + timedelta(days=2),
    )
    assert batch.manifest.packet_count == 1
    batch_path = tmp_path / "batch.json"
    batch_path.write_text(json.dumps(annotation_batch_to_dict(batch), sort_keys=True), encoding="utf-8")
    assert load_annotation_batch(batch_path) == batch

    packet = batch.packets[0]
    first = ReviewerSubmission.create(
        packet,
        reviewer_id="reviewer-a",
        submitted_at=BASE + timedelta(days=3),
        direction=StanceDirection.HAWKISH,
        disposition=EvidenceDisposition.SUPPORTED,
    )
    second = ReviewerSubmission.create(
        packet,
        reviewer_id="reviewer-b",
        submitted_at=BASE + timedelta(days=3, minutes=1),
        direction=StanceDirection.DOVISH,
        disposition=EvidenceDisposition.SUPPORTED,
    )
    adjudication = AdjudicationRecord.create(
        packet,
        (first, second),
        adjudicator_id="adjudicator-1",
        adjudicated_at=BASE + timedelta(days=4),
        direction=StanceDirection.HAWKISH,
        disposition=EvidenceDisposition.SUPPORTED,
    )
    submissions_path = tmp_path / "submissions.jsonl"
    adjudications_path = tmp_path / "adjudications.jsonl"
    write_jsonl(submissions_path, [reviewer_submission_to_dict(first), reviewer_submission_to_dict(second)])
    write_jsonl(adjudications_path, [adjudication_to_dict(adjudication)])

    finalized = finalize_annotation_files(
        database,
        batch_path,
        submissions_path,
        adjudications_path,
    )
    assert len(finalized) == 1
    result = finalized[0]
    assert result.audit.reviewer_overall_agreement is False
    assert result.semantic_label.source == "human_review"

    labels_path = tmp_path / "labels.jsonl"
    audit_path = tmp_path / "audit.jsonl"
    write_jsonl(labels_path, [semantic_label_to_dict(result.semantic_label)])
    write_jsonl(audit_path, [finalization_audit_to_dict(result.audit)])
    assert load_semantic_label_corpus(labels_path) == (result.semantic_label,)
    audit_record = json.loads(audit_path.read_text(encoding="utf-8"))
    assert audit_record["semantic_label_id"] == result.semantic_label.label_id
    assert audit_record["reviewer_overall_agreement"] is False
    assert audit_record["source_submission_ids"] == sorted((first.submission_id, second.submission_id))
    assert versions[1].version_id == result.semantic_label.current_version_id


def test_export_requires_frozen_cutoff_family_and_policy(tmp_path) -> None:
    database, _ = setup_database(tmp_path)
    with pytest.raises(ValueError, match="timezone-aware"):
        export_annotation_batch(
            database,
            family_id=FAMILY,
            annotation_policy_version=POLICY,
            as_of=BASE.replace(tzinfo=None),
        )
    with pytest.raises(ValueError, match="requires at least two"):
        export_annotation_batch(
            database,
            family_id="missing-family",
            annotation_policy_version=POLICY,
            as_of=BASE + timedelta(days=2),
        )
    with pytest.raises(ValueError, match="annotation_policy_version"):
        export_annotation_batch(
            database,
            family_id=FAMILY,
            annotation_policy_version=" ",
            as_of=BASE + timedelta(days=2),
        )


def test_parse_as_of_requires_timezone() -> None:
    assert _parse_as_of("2026-08-08T12:00:00+00:00") == BASE
    with pytest.raises(ValueError, match="timezone-aware"):
        _parse_as_of("2026-08-08T12:00:00")
