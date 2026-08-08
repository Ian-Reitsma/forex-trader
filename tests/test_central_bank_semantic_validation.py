from __future__ import annotations

import hashlib
import json
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from forex_trader.intelligence.official_documents import OfficialDocumentVersion, compare_document_versions
from forex_trader.research.central_bank_stance import (
    EvidenceDisposition,
    PolicyDimension,
    StanceDirection,
)
from forex_trader.research.stance_semantic_validation import (
    HUMAN_REVIEW_SOURCE,
    SEMANTIC_LABEL_SCHEMA_VERSION,
    CentralBankSemanticLabel,
    DimensionSemanticLabel,
    evaluate_semantic_labels,
    load_semantic_label_corpus,
    official_document_diff_id,
)


BASE = datetime(2026, 8, 8, 12, 0, tzinfo=UTC)
POLICY = "central-bank-stance-human-v1"


def version(
    *,
    family_id: str,
    suffix: str,
    text: str,
    available_at: datetime,
    predecessor_version_id: str | None,
    institution: str = "Federal Reserve",
    document_type: str = "monetary_policy_statement",
    currency: str = "USD",
) -> OfficialDocumentVersion:
    return OfficialDocumentVersion(
        family_id=family_id,
        source_id="official_test_source",
        document_type=document_type,
        institution=institution,
        currency=currency,
        discovery_id=hashlib.sha256(f"discovery-{family_id}-{suffix}".encode()).hexdigest(),
        item_id=f"item-{family_id}-{suffix}",
        document_url=f"https://www.federalreserve.gov/{family_id}-{suffix}.htm",
        published_at=available_at - timedelta(seconds=1),
        available_at=available_at,
        source_record_id=hashlib.sha256(f"record-{family_id}-{suffix}".encode()).hexdigest(),
        source_payload_sha256=hashlib.sha256(f"payload-{family_id}-{suffix}".encode()).hexdigest(),
        text_sha256=hashlib.sha256(text.encode()).hexdigest(),
        text=text,
        predecessor_version_id=predecessor_version_id,
    )


def pair(
    *,
    family_id: str,
    old_text: str,
    new_text: str,
    offset_days: int,
) -> tuple[OfficialDocumentVersion, OfficialDocumentVersion]:
    previous = version(
        family_id=family_id,
        suffix="previous",
        text=old_text,
        available_at=BASE + timedelta(days=offset_days - 30),
        predecessor_version_id=None,
    )
    current = version(
        family_id=family_id,
        suffix="current",
        text=new_text,
        available_at=BASE + timedelta(days=offset_days),
        predecessor_version_id=previous.version_id,
    )
    return previous, current


def label(
    previous: OfficialDocumentVersion,
    current: OfficialDocumentVersion,
    *,
    direction: StanceDirection,
    disposition: EvidenceDisposition,
    dimensions: tuple[DimensionSemanticLabel, ...] = (),
    adjudicated: bool = True,
    policy: str = POLICY,
) -> CentralBankSemanticLabel:
    return CentralBankSemanticLabel.create(
        compare_document_versions(previous, current),
        annotation_policy_version=policy,
        annotator_ids=("reviewer-a", "reviewer-b") if adjudicated else ("reviewer-a",),
        adjudicated=adjudicated,
        adjudicator_id="adjudicator-1" if adjudicated else None,
        labeled_at=current.available_at + timedelta(days=1),
        direction=direction,
        disposition=disposition,
        dimensions=dimensions,
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
        "dimensions": [
            {
                "dimension": dimension.dimension.value,
                "direction": dimension.direction.value,
                "disposition": dimension.disposition.value,
            }
            for dimension in item.dimensions
        ],
    }


def fixture_cases() -> tuple[
    tuple[OfficialDocumentVersion, OfficialDocumentVersion, CentralBankSemanticLabel], ...
]:
    inflation_supported = DimensionSemanticLabel(
        PolicyDimension.INFLATION,
        StanceDirection.HAWKISH,
        EvidenceDisposition.SUPPORTED,
    )
    inflation_ambiguous = DimensionSemanticLabel(
        PolicyDimension.INFLATION,
        StanceDirection.HAWKISH,
        EvidenceDisposition.AMBIGUOUS,
    )
    first = pair(
        family_id="fed_correct_hawkish",
        old_text="Inflation has eased.",
        new_text="Inflation remains elevated.",
        offset_days=0,
    )
    second = pair(
        family_id="fed_wrong_direction_fixture",
        old_text="Inflation remains elevated.",
        new_text="Inflation has eased.",
        offset_days=1,
    )
    third = pair(
        family_id="fed_abstention_fixture",
        old_text="The Committee met today.",
        new_text="The Committee met again.",
        offset_days=2,
    )
    fourth = pair(
        family_id="fed_contradiction_fixture",
        old_text="The Committee met today.",
        new_text="Inflation remains elevated. Inflation has eased.",
        offset_days=3,
    )
    fifth = pair(
        family_id="fed_ambiguous_fixture",
        old_text="The Committee met today.",
        new_text="If inflation remains elevated, policy may need to respond.",
        offset_days=4,
    )
    return (
        (*first, label(*first, direction=StanceDirection.HAWKISH, disposition=EvidenceDisposition.SUPPORTED, dimensions=(inflation_supported,))),
        (*second, label(*second, direction=StanceDirection.HAWKISH, disposition=EvidenceDisposition.SUPPORTED, dimensions=(inflation_supported,))),
        (*third, label(*third, direction=StanceDirection.NEUTRAL, disposition=EvidenceDisposition.ABSTAINED)),
        (*fourth, label(*fourth, direction=StanceDirection.CONTRADICTORY, disposition=EvidenceDisposition.CONTRADICTORY)),
        (*fifth, label(*fifth, direction=StanceDirection.HAWKISH, disposition=EvidenceDisposition.AMBIGUOUS, dimensions=(inflation_ambiguous,))),
    )


def test_semantic_label_is_source_bound_adjudicated_and_non_executable() -> None:
    previous, current = pair(
        family_id="fed_label_contract",
        old_text="Inflation has eased.",
        new_text="Inflation remains elevated.",
        offset_days=0,
    )
    diff = compare_document_versions(previous, current)
    item = label(previous, current, direction=StanceDirection.HAWKISH, disposition=EvidenceDisposition.SUPPORTED)
    assert item.schema_version == SEMANTIC_LABEL_SCHEMA_VERSION
    assert item.source == HUMAN_REVIEW_SOURCE
    assert item.research_only is True
    assert item.execution_authority is False
    assert item.diff_id == official_document_diff_id(diff)
    assert len(item.label_id) == 64
    assert item.annotator_ids == ("reviewer-a", "reviewer-b")
    with pytest.raises(ValueError, match="ID does not match"):
        replace(item, diff_id="0" * 64)


def test_adjudication_requires_two_reviewers_and_adjudicator() -> None:
    previous, current = pair(
        family_id="fed_adjudication_contract",
        old_text="The Committee met today.",
        new_text="Inflation remains elevated.",
        offset_days=0,
    )
    diff = compare_document_versions(previous, current)
    with pytest.raises(ValueError, match="at least two"):
        CentralBankSemanticLabel.create(
            diff,
            annotation_policy_version=POLICY,
            annotator_ids=("one-reviewer",),
            adjudicated=True,
            adjudicator_id="adjudicator",
            labeled_at=BASE,
            direction=StanceDirection.HAWKISH,
            disposition=EvidenceDisposition.SUPPORTED,
        )
    with pytest.raises(ValueError, match="requires an adjudicator"):
        CentralBankSemanticLabel.create(
            diff,
            annotation_policy_version=POLICY,
            annotator_ids=("a", "b"),
            adjudicated=True,
            adjudicator_id=None,
            labeled_at=BASE,
            direction=StanceDirection.HAWKISH,
            disposition=EvidenceDisposition.SUPPORTED,
        )


def test_semantic_evaluation_reports_full_error_denominators_and_dimensions() -> None:
    cases = fixture_cases()
    versions = tuple(version for previous, current, _ in cases for version in (previous, current))
    labels = tuple(item for _, _, item in cases)
    unadjudicated = label(
        cases[0][0],
        cases[0][1],
        direction=StanceDirection.HAWKISH,
        disposition=EvidenceDisposition.SUPPORTED,
        adjudicated=False,
    )
    report = evaluate_semantic_labels((*labels, unadjudicated), versions)

    assert report.research_only is True
    assert report.execution_authority is False
    assert report.total_label_records == 6
    assert report.adjudicated_label_records == 5
    assert report.unadjudicated_label_records == 1
    assert report.evaluated_labels == 5
    assert report.exact_direction_accuracy == Decimal("0.8")
    assert report.exact_disposition_accuracy == Decimal("1")
    assert report.abstention_rate == Decimal("0.2")
    assert report.directional_truth_count == 3
    assert report.directional_truth_coverage == Decimal("1")
    assert report.directional_truth_exact_recall == Decimal(2) / Decimal(3)
    assert report.directional_call_count == 3
    assert report.false_direction_rate_when_called == Decimal(1) / Decimal(3)
    assert report.truth_contradictory_count == 1
    assert report.contradiction_recall == Decimal("1")
    assert report.truth_ambiguous_disposition_count == 1
    assert report.ambiguous_disposition_recall == Decimal("1")
    assert report.excluded_unadjudicated_label_ids == (unadjudicated.label_id,)
    assert len(report.report_id) == 64

    inflation = next(item for item in report.dimensions if item.dimension is PolicyDimension.INFLATION)
    assert inflation.sample_size == 3
    assert inflation.prediction_present_count == 3
    assert inflation.exact_direction_accuracy == Decimal(2) / Decimal(3)
    assert inflation.exact_disposition_accuracy == Decimal("1")
    assert len(report.cohorts) == 5


def test_semantic_report_is_deterministic_under_input_order() -> None:
    cases = fixture_cases()
    versions = tuple(version for previous, current, _ in cases for version in (previous, current))
    labels = tuple(item for _, _, item in cases)
    first = evaluate_semantic_labels(labels, versions)
    second = evaluate_semantic_labels(reversed(labels), reversed(versions))
    assert first.report_id == second.report_id
    assert first.confusion == second.confusion
    assert first.cohorts == second.cohorts


def test_evaluation_fails_on_duplicate_ground_truth_mixed_policy_or_missing_versions() -> None:
    previous, current, item = fixture_cases()[0]
    duplicate_diff_label = CentralBankSemanticLabel.create(
        compare_document_versions(previous, current),
        annotation_policy_version=POLICY,
        annotator_ids=("reviewer-c", "reviewer-d"),
        adjudicated=True,
        adjudicator_id="adjudicator-2",
        labeled_at=current.available_at + timedelta(days=2),
        direction=StanceDirection.HAWKISH,
        disposition=EvidenceDisposition.SUPPORTED,
    )
    with pytest.raises(ValueError, match="multiple adjudicated labels"):
        evaluate_semantic_labels((item, duplicate_diff_label), (previous, current))

    alternate_pair = pair(
        family_id="fed_other_policy",
        old_text="Inflation has eased.",
        new_text="Inflation remains elevated.",
        offset_days=8,
    )
    alternate_policy = label(
        *alternate_pair,
        direction=StanceDirection.HAWKISH,
        disposition=EvidenceDisposition.SUPPORTED,
        policy="human-policy-v2",
    )
    with pytest.raises(ValueError, match="cannot mix"):
        evaluate_semantic_labels((item, alternate_policy), (previous, current, *alternate_pair))
    with pytest.raises(ValueError, match="absent"):
        evaluate_semantic_labels((item,), (previous,))


def test_unadjudicated_only_corpus_cannot_claim_semantic_evaluation() -> None:
    previous, current = pair(
        family_id="fed_unadjudicated_only",
        old_text="The Committee met today.",
        new_text="Inflation remains elevated.",
        offset_days=0,
    )
    item = label(
        previous,
        current,
        direction=StanceDirection.HAWKISH,
        disposition=EvidenceDisposition.SUPPORTED,
        adjudicated=False,
    )
    with pytest.raises(ValueError, match="at least one adjudicated"):
        evaluate_semantic_labels((item,), (previous, current))


def test_label_loader_round_trips_valid_records_and_rejects_unsafe_json(tmp_path) -> None:
    previous, current, item = fixture_cases()[0]
    del previous, current
    path = tmp_path / "labels.jsonl"
    path.write_text(json.dumps(label_record(item)) + "\n", encoding="utf-8")
    assert load_semantic_label_corpus(path) == (item,)

    path.write_text("not-json\n", encoding="utf-8")
    with pytest.raises(ValueError, match="not valid JSON"):
        load_semantic_label_corpus(path)
    path.write_text(json.dumps({**label_record(item), "research_only": "true"}) + "\n", encoding="utf-8")
    with pytest.raises(ValueError, match="JSON boolean"):
        load_semantic_label_corpus(path)
    path.write_text("\n", encoding="utf-8")
    with pytest.raises(ValueError, match="empty"):
        load_semantic_label_corpus(path)


def test_direction_disposition_contract_rejects_incoherent_human_truth() -> None:
    with pytest.raises(ValueError, match="contradictory direction"):
        DimensionSemanticLabel(
            PolicyDimension.INFLATION,
            StanceDirection.CONTRADICTORY,
            EvidenceDisposition.SUPPORTED,
        )
    with pytest.raises(ValueError, match="abstained disposition"):
        DimensionSemanticLabel(
            PolicyDimension.GROWTH,
            StanceDirection.HAWKISH,
            EvidenceDisposition.ABSTAINED,
        )
