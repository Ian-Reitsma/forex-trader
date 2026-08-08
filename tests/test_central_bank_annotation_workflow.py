from __future__ import annotations

import hashlib
import json
from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pytest

from forex_trader.intelligence.official_documents import OfficialDocumentVersion
from forex_trader.research.central_bank_stance import (
    EvidenceDisposition,
    PolicyDimension,
    StanceDirection,
)
from forex_trader.research.stance_annotation_workflow import (
    AdjudicationRecord,
    ReviewerSubmission,
    adjudication_to_dict,
    annotation_batch_to_dict,
    build_blinded_annotation_batch,
    finalize_annotation_batch,
    load_adjudications,
    load_annotation_batch,
    load_reviewer_submissions,
    reviewer_submission_to_dict,
)
from forex_trader.research.stance_semantic_validation import (
    DimensionSemanticLabel,
    evaluate_semantic_labels,
)


BASE = datetime(2026, 8, 8, 12, 0, tzinfo=UTC)
FAMILY = "fed_fomc_annotation_fixture"
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
        document_url=f"https://www.federalreserve.gov/annotation-{suffix}.htm",
        published_at=available_at - timedelta(seconds=1),
        available_at=available_at,
        source_record_id=hashlib.sha256(f"record-{suffix}".encode()).hexdigest(),
        source_payload_sha256=hashlib.sha256(f"payload-{suffix}".encode()).hexdigest(),
        text_sha256=hashlib.sha256(text.encode()).hexdigest(),
        text=text,
        predecessor_version_id=predecessor_version_id,
    )


def source_versions() -> tuple[OfficialDocumentVersion, ...]:
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
    third = version(
        index=2,
        text="The Committee met today.\nInflation has eased.",
        available_at=BASE + timedelta(days=2),
        predecessor_version_id=second.version_id,
    )
    fourth = version(
        index=3,
        text="The Committee met today.\nGrowth has slowed.",
        available_at=BASE + timedelta(days=3),
        predecessor_version_id=third.version_id,
    )
    return first, second, third, fourth


def batch_two_packets():  # type: ignore[no-untyped-def]
    versions = source_versions()
    batch = build_blinded_annotation_batch(
        reversed(versions),
        annotation_policy_version=POLICY,
        as_of=BASE + timedelta(days=2, hours=12),
    )
    return versions, batch


def review(
    packet,  # type: ignore[no-untyped-def]
    reviewer_id: str,
    *,
    offset_minutes: int,
    direction: StanceDirection,
    disposition: EvidenceDisposition,
    dimensions: tuple[DimensionSemanticLabel, ...] = (),
) -> ReviewerSubmission:
    return ReviewerSubmission.create(
        packet,
        reviewer_id=reviewer_id,
        submitted_at=BASE + timedelta(days=10, minutes=offset_minutes),
        direction=direction,
        disposition=disposition,
        dimensions=dimensions,
    )


def adjudicate(
    packet,  # type: ignore[no-untyped-def]
    submissions: tuple[ReviewerSubmission, ...],
    *,
    direction: StanceDirection,
    disposition: EvidenceDisposition,
    dimensions: tuple[DimensionSemanticLabel, ...] = (),
) -> AdjudicationRecord:
    return AdjudicationRecord.create(
        packet,
        submissions,
        adjudicator_id="adjudicator-1",
        adjudicated_at=BASE + timedelta(days=11),
        direction=direction,
        disposition=disposition,
        dimensions=dimensions,
    )


def test_frozen_batch_is_complete_deterministic_and_model_blind() -> None:
    versions, batch = batch_two_packets()
    assert batch.manifest.packet_count == 2
    assert tuple(item.current_version_id for item in batch.packets) == (
        versions[1].version_id,
        versions[2].version_id,
    )
    assert all(item.current_available_at <= batch.manifest.as_of for item in batch.packets)
    same = build_blinded_annotation_batch(
        versions,
        annotation_policy_version=POLICY,
        as_of=batch.manifest.as_of,
    )
    assert same == batch

    payload = annotation_batch_to_dict(batch)
    packet = payload["packets"][0]  # type: ignore[index]
    assert isinstance(packet, dict)
    forbidden = {
        "model_prediction",
        "prediction",
        "stance_direction",
        "stance_disposition",
        "ruleset_version",
        "rule_id",
        "evidence_quality",
        "score",
        "market_return",
        "market_return_bps",
        "outcome",
    }
    assert forbidden.isdisjoint(packet)
    assert packet["previous_text"] == versions[0].text
    assert packet["current_text"] == versions[1].text
    assert packet["added"]
    assert len(batch.manifest.batch_id) == 64


def test_packet_identity_and_source_hashes_detect_tampering() -> None:
    _, batch = batch_two_packets()
    packet = batch.packets[0]
    with pytest.raises(ValueError, match="current text hash"):
        replace(packet, current_text=packet.current_text + " tampered")
    with pytest.raises(ValueError, match="packet ID"):
        replace(packet, annotation_policy_version="changed-policy")


def test_batch_loader_rejects_hidden_model_fields_and_round_trips(tmp_path) -> None:
    _, batch = batch_two_packets()
    payload = annotation_batch_to_dict(batch)
    path = tmp_path / "batch.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    assert load_annotation_batch(path) == batch

    packets = payload["packets"]
    assert isinstance(packets, list)
    assert isinstance(packets[0], dict)
    packets[0]["model_prediction"] = "hawkish"
    path.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(ValueError, match="unexpected=.*model_prediction"):
        load_annotation_batch(path)


def test_reviewers_are_independent_and_adjudicator_cannot_be_reviewer() -> None:
    _, batch = batch_two_packets()
    packet = batch.packets[0]
    first = review(
        packet,
        "reviewer-a",
        offset_minutes=1,
        direction=StanceDirection.HAWKISH,
        disposition=EvidenceDisposition.SUPPORTED,
    )
    same_reviewer = review(
        packet,
        "reviewer-a",
        offset_minutes=2,
        direction=StanceDirection.DOVISH,
        disposition=EvidenceDisposition.SUPPORTED,
    )
    with pytest.raises(ValueError, match="independent pseudonymous"):
        AdjudicationRecord.create(
            packet,
            (first, same_reviewer),
            adjudicator_id="adjudicator-1",
            adjudicated_at=BASE + timedelta(days=11),
            direction=StanceDirection.HAWKISH,
            disposition=EvidenceDisposition.SUPPORTED,
        )
    second = review(
        packet,
        "reviewer-b",
        offset_minutes=2,
        direction=StanceDirection.DOVISH,
        disposition=EvidenceDisposition.SUPPORTED,
    )
    with pytest.raises(ValueError, match="adjudicator must be independent"):
        AdjudicationRecord.create(
            packet,
            (first, second),
            adjudicator_id="reviewer-a",
            adjudicated_at=BASE + timedelta(days=11),
            direction=StanceDirection.HAWKISH,
            disposition=EvidenceDisposition.SUPPORTED,
        )


def test_full_batch_finalization_preserves_disagreement_and_accepts_version_generator() -> None:
    versions, batch = batch_two_packets()
    inflation_hawkish = DimensionSemanticLabel(
        PolicyDimension.INFLATION,
        StanceDirection.HAWKISH,
        EvidenceDisposition.SUPPORTED,
    )
    inflation_dovish = DimensionSemanticLabel(
        PolicyDimension.INFLATION,
        StanceDirection.DOVISH,
        EvidenceDisposition.SUPPORTED,
    )
    submissions: list[ReviewerSubmission] = []
    adjudications: list[AdjudicationRecord] = []

    first_packet = batch.packets[0]
    first_reviews = (
        review(
            first_packet,
            "reviewer-a",
            offset_minutes=1,
            direction=StanceDirection.HAWKISH,
            disposition=EvidenceDisposition.SUPPORTED,
            dimensions=(inflation_hawkish,),
        ),
        review(
            first_packet,
            "reviewer-b",
            offset_minutes=2,
            direction=StanceDirection.DOVISH,
            disposition=EvidenceDisposition.SUPPORTED,
            dimensions=(inflation_dovish,),
        ),
    )
    submissions.extend(first_reviews)
    adjudications.append(
        adjudicate(
            first_packet,
            first_reviews,
            direction=StanceDirection.HAWKISH,
            disposition=EvidenceDisposition.SUPPORTED,
            dimensions=(inflation_hawkish,),
        )
    )

    second_packet = batch.packets[1]
    second_reviews = (
        review(
            second_packet,
            "reviewer-a",
            offset_minutes=3,
            direction=StanceDirection.DOVISH,
            disposition=EvidenceDisposition.SUPPORTED,
            dimensions=(inflation_dovish,),
        ),
        review(
            second_packet,
            "reviewer-b",
            offset_minutes=4,
            direction=StanceDirection.DOVISH,
            disposition=EvidenceDisposition.SUPPORTED,
            dimensions=(inflation_dovish,),
        ),
    )
    submissions.extend(second_reviews)
    adjudications.append(
        adjudicate(
            second_packet,
            second_reviews,
            direction=StanceDirection.DOVISH,
            disposition=EvidenceDisposition.SUPPORTED,
            dimensions=(inflation_dovish,),
        )
    )

    finalized = finalize_annotation_batch(batch, submissions, adjudications, iter(versions))
    assert len(finalized) == 2
    first, second = finalized
    assert first.audit.reviewer_overall_agreement is False
    assert first.audit.reviewer_dimension_agreement is False
    assert second.audit.reviewer_overall_agreement is True
    assert second.audit.reviewer_dimension_agreement is True
    assert first.semantic_label.annotator_ids == ("reviewer-a", "reviewer-b")
    assert first.semantic_label.adjudicator_id == "adjudicator-1"
    assert first.semantic_label.source == "human_review"
    assert first.semantic_label.research_only is True
    assert first.semantic_label.execution_authority is False

    report = evaluate_semantic_labels(
        tuple(item.semantic_label for item in finalized),
        versions,
    )
    assert report.evaluated_labels == 2
    assert report.unadjudicated_label_records == 0


def test_adjudication_must_account_for_every_submission_and_every_batch_packet() -> None:
    versions, batch = batch_two_packets()
    packet = batch.packets[0]
    first = review(
        packet,
        "reviewer-a",
        offset_minutes=1,
        direction=StanceDirection.HAWKISH,
        disposition=EvidenceDisposition.SUPPORTED,
    )
    second = review(
        packet,
        "reviewer-b",
        offset_minutes=2,
        direction=StanceDirection.HAWKISH,
        disposition=EvidenceDisposition.SUPPORTED,
    )
    third = review(
        packet,
        "reviewer-c",
        offset_minutes=3,
        direction=StanceDirection.DOVISH,
        disposition=EvidenceDisposition.SUPPORTED,
    )
    partial_adjudication = adjudicate(
        packet,
        (first, second),
        direction=StanceDirection.HAWKISH,
        disposition=EvidenceDisposition.SUPPORTED,
    )
    with pytest.raises(ValueError, match="account for every reviewer submission"):
        finalize_annotation_batch(
            build_blinded_annotation_batch(
                versions[:2],
                annotation_policy_version=POLICY,
                as_of=BASE + timedelta(days=1, hours=1),
            ),
            (first, second, third),
            (partial_adjudication,),
            versions[:2],
        )

    complete_first = adjudicate(
        packet,
        (first, second),
        direction=StanceDirection.HAWKISH,
        disposition=EvidenceDisposition.SUPPORTED,
    )
    with pytest.raises(ValueError, match="at least two independent reviewer"):
        finalize_annotation_batch(batch, (first, second), (complete_first,), versions)


def test_submission_and_adjudication_loaders_reject_hidden_fields(tmp_path) -> None:
    _, batch = batch_two_packets()
    packet = batch.packets[0]
    first = review(
        packet,
        "reviewer-a",
        offset_minutes=1,
        direction=StanceDirection.HAWKISH,
        disposition=EvidenceDisposition.SUPPORTED,
    )
    second = review(
        packet,
        "reviewer-b",
        offset_minutes=2,
        direction=StanceDirection.HAWKISH,
        disposition=EvidenceDisposition.SUPPORTED,
    )
    adjudication = adjudicate(
        packet,
        (first, second),
        direction=StanceDirection.HAWKISH,
        disposition=EvidenceDisposition.SUPPORTED,
    )

    submissions_path = tmp_path / "submissions.jsonl"
    submissions_path.write_text(
        json.dumps(reviewer_submission_to_dict(first)) + "\n" + json.dumps(reviewer_submission_to_dict(second)) + "\n",
        encoding="utf-8",
    )
    assert load_reviewer_submissions(submissions_path) == (first, second)
    contaminated = reviewer_submission_to_dict(first)
    contaminated["market_return_bps"] = "12"
    submissions_path.write_text(json.dumps(contaminated) + "\n", encoding="utf-8")
    with pytest.raises(ValueError, match="market_return_bps"):
        load_reviewer_submissions(submissions_path)

    adjudications_path = tmp_path / "adjudications.jsonl"
    adjudications_path.write_text(json.dumps(adjudication_to_dict(adjudication)) + "\n", encoding="utf-8")
    assert load_adjudications(adjudications_path) == (adjudication,)
    contaminated_adjudication = adjudication_to_dict(adjudication)
    contaminated_adjudication["model_score"] = "0.9"
    adjudications_path.write_text(json.dumps(contaminated_adjudication) + "\n", encoding="utf-8")
    with pytest.raises(ValueError, match="model_score"):
        load_adjudications(adjudications_path)
