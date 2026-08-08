from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from forex_trader.infrastructure.official_document_repository import OfficialDocumentRepository
from forex_trader.intelligence.official_documents import OfficialDocumentVersion
from forex_trader.research.central_bank_stance import EvidenceDisposition, PolicyDimension, StanceDirection
from forex_trader.research.central_bank_stance_baselines import trivial_stance_baselines
from forex_trader.research.central_bank_stance_evaluation import (
    ExpectedDimensionLabel,
    StanceEvaluationDataset,
    StanceEvaluationLabel,
    evaluate_stance_dataset,
    load_stance_labels,
)


BASE = datetime(2026, 1, 1, tzinfo=UTC)


def version(
    *,
    family: str,
    suffix: str,
    text: str,
    available_at: datetime,
    predecessor: str | None,
    institution: str = "Federal Reserve",
    document_type: str = "monetary_policy_statement",
) -> OfficialDocumentVersion:
    return OfficialDocumentVersion(
        family_id=family,
        source_id="federal_reserve",
        document_type=document_type,
        institution=institution,
        currency="USD",
        discovery_id=hashlib.sha256(f"discovery:{family}:{suffix}".encode()).hexdigest(),
        item_id=f"{family}:{suffix}",
        document_url=f"https://www.federalreserve.gov/{family}-{suffix}.htm",
        published_at=available_at - timedelta(seconds=1),
        available_at=available_at,
        source_record_id=hashlib.sha256(f"record:{family}:{suffix}".encode()).hexdigest(),
        source_payload_sha256=hashlib.sha256(f"payload:{family}:{suffix}".encode()).hexdigest(),
        text_sha256=hashlib.sha256(text.encode()).hexdigest(),
        text=text,
        predecessor_version_id=predecessor,
    )


def add_pair(
    repository: OfficialDocumentRepository,
    *,
    family: str,
    first_text: str,
    second_text: str,
    offset: int,
    institution: str = "Federal Reserve",
) -> tuple[OfficialDocumentVersion, OfficialDocumentVersion]:
    first = version(
        family=family,
        suffix="first",
        text=first_text,
        available_at=BASE + timedelta(minutes=offset),
        predecessor=None,
        institution=institution,
    )
    repository.append(first)
    second = version(
        family=family,
        suffix="second",
        text=second_text,
        available_at=BASE + timedelta(minutes=offset + 1),
        predecessor=first.version_id,
        institution=institution,
    )
    repository.append(second)
    return first, second


def label(
    first: OfficialDocumentVersion,
    second: OfficialDocumentVersion,
    direction: StanceDirection,
    disposition: EvidenceDisposition,
    *,
    dimensions: tuple[ExpectedDimensionLabel, ...] = (),
    source: str = "human-review-batch-001",
) -> StanceEvaluationLabel:
    return StanceEvaluationLabel(
        family_id=first.family_id,
        previous_version_id=first.version_id,
        current_version_id=second.version_id,
        expected_direction=direction,
        expected_disposition=disposition,
        label_source_id=source,
        dimensions=dimensions,
    )


def evaluation_fixture(tmp_path):  # type: ignore[no-untyped-def]
    repository = OfficialDocumentRepository(tmp_path / "documents.db")
    dovish = add_pair(
        repository,
        family="fed-dovish",
        first_text="Inflation remains elevated.",
        second_text="Inflation has eased.",
        offset=0,
    )
    false_directional = add_pair(
        repository,
        family="fed-human-neutral",
        first_text="Inflation has eased.",
        second_text="The meeting concluded.",
        offset=10,
    )
    hawkish = add_pair(
        repository,
        family="fed-hawkish",
        first_text="The meeting concluded.",
        second_text="Inflation remains elevated.",
        offset=20,
    )
    contradictory = add_pair(
        repository,
        family="fed-contradictory",
        first_text="The meeting concluded.",
        second_text="Inflation remains elevated.\nThe Committee decided to lower the target range.",
        offset=30,
    )
    abstain = add_pair(
        repository,
        family="fed-abstain",
        first_text="The meeting began.",
        second_text="The meeting concluded.",
        offset=40,
    )
    labels = StanceEvaluationDataset(
        (
            label(
                *dovish,
                StanceDirection.DOVISH,
                EvidenceDisposition.SUPPORTED,
                dimensions=(ExpectedDimensionLabel(PolicyDimension.INFLATION, StanceDirection.DOVISH),),
            ),
            label(*false_directional, StanceDirection.NEUTRAL, EvidenceDisposition.ABSTAINED),
            label(
                *hawkish,
                StanceDirection.HAWKISH,
                EvidenceDisposition.SUPPORTED,
                dimensions=(ExpectedDimensionLabel(PolicyDimension.INFLATION, StanceDirection.HAWKISH),),
            ),
            label(*contradictory, StanceDirection.CONTRADICTORY, EvidenceDisposition.CONTRADICTORY),
            label(*abstain, StanceDirection.NEUTRAL, EvidenceDisposition.ABSTAINED),
        )
    )
    return repository, labels


def test_evaluation_reports_coverage_false_direction_contradiction_and_dimensions(tmp_path) -> None:
    repository, dataset = evaluation_fixture(tmp_path)
    report = evaluate_stance_dataset(dataset, repository)

    assert report.research_only is True
    assert report.execution_authority is False
    assert report.total_labels == 5
    assert report.covered_predictions == 4
    assert report.abstentions == 1
    assert report.coverage == Decimal("0.8")
    assert report.abstention_rate == Decimal("0.2")
    assert report.direction_accuracy == Decimal("0.8")
    assert report.disposition_accuracy == Decimal("0.8")
    assert report.exact_accuracy == Decimal("0.8")
    assert report.directional_accuracy_when_covered == Decimal("0.75")
    assert report.false_directional_rate == Decimal("0.2")
    assert report.contradiction_recall == Decimal("1")
    assert report.dimension_accuracy == Decimal("1")
    assert report.confusion["neutral"]["hawkish"] == 1
    assert report.confusion["contradictory"]["contradictory"] == 1
    assert len(report.cohorts) == 15
    assert report.dataset_id == dataset.dataset_id


def test_dataset_digest_is_order_independent_but_label_provenance_changes_identity(tmp_path) -> None:
    _, dataset = evaluation_fixture(tmp_path)
    reversed_dataset = StanceEvaluationDataset(tuple(reversed(dataset.labels)))
    assert dataset.dataset_id == reversed_dataset.dataset_id

    original = dataset.labels[0]
    relabeled = StanceEvaluationLabel(
        family_id=original.family_id,
        previous_version_id=original.previous_version_id,
        current_version_id=original.current_version_id,
        expected_direction=original.expected_direction,
        expected_disposition=original.expected_disposition,
        label_source_id="human-review-batch-002",
        dimensions=original.dimensions,
    )
    assert original.label_id != relabeled.label_id


def test_dataset_rejects_duplicate_pairs_empty_labels_bad_hashes_and_duplicate_dimensions(tmp_path) -> None:
    _, dataset = evaluation_fixture(tmp_path)
    with pytest.raises(ValueError, match="cannot be empty"):
        StanceEvaluationDataset(())
    with pytest.raises(ValueError, match="duplicate version pairs"):
        StanceEvaluationDataset((dataset.labels[0], dataset.labels[0]))
    with pytest.raises(ValueError, match="SHA-256"):
        StanceEvaluationLabel(
            family_id="x",
            previous_version_id="bad",
            current_version_id="b" * 64,
            expected_direction=StanceDirection.NEUTRAL,
            expected_disposition=EvidenceDisposition.ABSTAINED,
            label_source_id="review",
        )
    first = dataset.labels[0]
    with pytest.raises(ValueError, match="dimension labels must be unique"):
        StanceEvaluationLabel(
            family_id=first.family_id,
            previous_version_id=first.previous_version_id,
            current_version_id=first.current_version_id,
            expected_direction=first.expected_direction,
            expected_disposition=first.expected_disposition,
            label_source_id="review",
            dimensions=(
                ExpectedDimensionLabel(PolicyDimension.INFLATION, StanceDirection.DOVISH),
                ExpectedDimensionLabel(PolicyDimension.INFLATION, StanceDirection.HAWKISH),
            ),
        )


def test_evaluation_rejects_missing_wrong_family_and_nonadjacent_version_evidence(tmp_path) -> None:
    repository, dataset = evaluation_fixture(tmp_path)
    base = dataset.labels[0]
    missing = StanceEvaluationDataset(
        (
            StanceEvaluationLabel(
                family_id=base.family_id,
                previous_version_id=base.previous_version_id,
                current_version_id="f" * 64,
                expected_direction=base.expected_direction,
                expected_disposition=base.expected_disposition,
                label_source_id="review",
            ),
        )
    )
    with pytest.raises(ValueError, match="missing document version"):
        evaluate_stance_dataset(missing, repository)

    wrong_family = StanceEvaluationDataset(
        (
            StanceEvaluationLabel(
                family_id="wrong-family",
                previous_version_id=base.previous_version_id,
                current_version_id=base.current_version_id,
                expected_direction=base.expected_direction,
                expected_disposition=base.expected_disposition,
                label_source_id="review",
            ),
        )
    )
    with pytest.raises(ValueError, match="family_id"):
        evaluate_stance_dataset(wrong_family, repository)

    first_pair = dataset.labels[0]
    unrelated_current = dataset.labels[2].current_version_id
    nonadjacent = StanceEvaluationDataset(
        (
            StanceEvaluationLabel(
                family_id=first_pair.family_id,
                previous_version_id=first_pair.previous_version_id,
                current_version_id=unrelated_current,
                expected_direction=StanceDirection.NEUTRAL,
                expected_disposition=EvidenceDisposition.ABSTAINED,
                label_source_id="review",
            ),
        )
    )
    with pytest.raises(ValueError, match="family_id"):
        evaluate_stance_dataset(nonadjacent, repository)


def test_label_loader_parses_jsonl_and_rejects_invalid_lines(tmp_path) -> None:
    repository, dataset = evaluation_fixture(tmp_path)
    del repository
    path = tmp_path / "labels.jsonl"
    with path.open("w", encoding="utf-8") as handle:
        for item in dataset.labels[:2]:
            handle.write(
                json.dumps(
                    {
                        "family_id": item.family_id,
                        "previous_version_id": item.previous_version_id,
                        "current_version_id": item.current_version_id,
                        "expected_direction": item.expected_direction.value,
                        "expected_disposition": item.expected_disposition.value,
                        "label_source_id": item.label_source_id,
                        "dimensions": [
                            {"dimension": value.dimension.value, "direction": value.direction.value}
                            for value in item.dimensions
                        ],
                    }
                )
                + "\n"
            )
    loaded = load_stance_labels(str(path))
    assert loaded.labels == dataset.labels[:2]

    bad = tmp_path / "bad.jsonl"
    bad.write_text("not json\n", encoding="utf-8")
    with pytest.raises(ValueError, match="invalid JSON"):
        load_stance_labels(str(bad))


def test_trivial_baselines_expose_context_including_false_directional_rate(tmp_path) -> None:
    _, dataset = evaluation_fixture(tmp_path)
    baselines = {item.name: item for item in trivial_stance_baselines(dataset)}
    assert baselines["always_abstain"].direction_accuracy == Decimal("0.4")
    assert baselines["always_abstain"].false_directional_rate == Decimal("0")
    assert baselines["always_hawkish"].direction_accuracy == Decimal("0.2")
    assert baselines["always_hawkish"].false_directional_rate == Decimal("0.6")
    assert baselines["always_dovish"].direction_accuracy == Decimal("0.2")
    assert baselines["always_dovish"].false_directional_rate == Decimal("0.6")
