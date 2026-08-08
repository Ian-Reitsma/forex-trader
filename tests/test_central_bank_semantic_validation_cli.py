from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime, timedelta

import pytest

from scripts.evaluate_central_bank_stance_semantics import evaluate_semantic_corpus
from forex_trader.infrastructure.official_document_repository import OfficialDocumentRepository
from forex_trader.intelligence.official_documents import OfficialDocumentVersion, compare_document_versions
from forex_trader.research.central_bank_stance import EvidenceDisposition, StanceDirection
from forex_trader.research.stance_semantic_validation import CentralBankSemanticLabel


BASE = datetime(2026, 8, 8, 12, 0, tzinfo=UTC)


def version(
    *,
    suffix: str,
    text: str,
    available_at: datetime,
    predecessor_version_id: str | None,
) -> OfficialDocumentVersion:
    family = "fed_fomc_semantic_cli"
    return OfficialDocumentVersion(
        family_id=family,
        source_id="federal_reserve",
        document_type="monetary_policy_statement",
        institution="Federal Reserve",
        currency="USD",
        discovery_id=hashlib.sha256(f"discovery-{suffix}".encode()).hexdigest(),
        item_id=f"item-{suffix}",
        document_url=f"https://www.federalreserve.gov/semantic-{suffix}.htm",
        published_at=available_at - timedelta(seconds=1),
        available_at=available_at,
        source_record_id=hashlib.sha256(f"record-{suffix}".encode()).hexdigest(),
        source_payload_sha256=hashlib.sha256(f"payload-{suffix}".encode()).hexdigest(),
        text_sha256=hashlib.sha256(text.encode()).hexdigest(),
        text=text,
        predecessor_version_id=predecessor_version_id,
    )


def label_record(item: CentralBankSemanticLabel) -> dict[str, object]:
    return {
        "label_id": item.label_id,
        "schema_version": item.schema_version,
        "research_only": item.research_only,
        "execution_authority": item.execution_authority,
        "source": item.source,
        "diff_id": item.diff_id,
        "family_id": item.family_id,
        "previous_version_id": item.previous_version_id,
        "current_version_id": item.current_version_id,
        "annotation_policy_version": item.annotation_policy_version,
        "annotator_ids": list(item.annotator_ids),
        "adjudicated": item.adjudicated,
        "adjudicator_id": item.adjudicator_id,
        "labeled_at": item.labeled_at.isoformat(),
        "direction": item.direction.value,
        "disposition": item.disposition.value,
        "dimensions": [],
    }


def setup_corpus(tmp_path):  # type: ignore[no-untyped-def]
    database = tmp_path / "documents.db"
    labels_path = tmp_path / "labels.jsonl"
    repository = OfficialDocumentRepository(database)
    previous = version(
        suffix="previous",
        text="Inflation has eased.",
        available_at=BASE - timedelta(days=30),
        predecessor_version_id=None,
    )
    current = version(
        suffix="current",
        text="Inflation remains elevated.",
        available_at=BASE,
        predecessor_version_id=previous.version_id,
    )
    repository.append(previous)
    repository.append(current)
    label = CentralBankSemanticLabel.create(
        compare_document_versions(previous, current),
        annotation_policy_version="human-policy-v1",
        annotator_ids=("reviewer-1", "reviewer-2"),
        adjudicated=True,
        adjudicator_id="adjudicator-1",
        labeled_at=BASE + timedelta(hours=1),
        direction=StanceDirection.HAWKISH,
        disposition=EvidenceDisposition.SUPPORTED,
    )
    labels_path.write_text(json.dumps(label_record(label)) + "\n", encoding="utf-8")
    return database, labels_path, label


def test_offline_semantic_evaluator_reads_persisted_versions_and_human_labels(tmp_path) -> None:
    database, labels_path, label = setup_corpus(tmp_path)
    report = evaluate_semantic_corpus(database, labels_path)
    assert report.evaluated_labels == 1
    assert report.exact_direction_accuracy == 1
    assert report.exact_disposition_accuracy == 1
    assert report.evaluated_label_ids == (label.label_id,)
    assert report.research_only is True
    assert report.execution_authority is False


def test_offline_semantic_evaluator_fails_if_source_version_is_missing(tmp_path) -> None:
    database, labels_path, _ = setup_corpus(tmp_path)
    empty_database = tmp_path / "empty.db"
    OfficialDocumentRepository(empty_database)
    with pytest.raises(ValueError, match="missing document version"):
        evaluate_semantic_corpus(empty_database, labels_path)
    assert database.exists()


def test_offline_semantic_evaluator_does_not_accept_empty_or_missing_label_corpus(tmp_path) -> None:
    database, _, _ = setup_corpus(tmp_path)
    empty = tmp_path / "empty.jsonl"
    empty.write_text("\n", encoding="utf-8")
    with pytest.raises(ValueError, match="empty"):
        evaluate_semantic_corpus(database, empty)
    with pytest.raises(FileNotFoundError):
        evaluate_semantic_corpus(database, tmp_path / "missing.jsonl")
