from __future__ import annotations

import hashlib
from decimal import Decimal

import pytest

from forex_trader.intelligence.official_documents import DocumentTextChange, OfficialDocumentDiff
from forex_trader.research.central_bank_stance import (
    STANCE_RULESET_VERSION,
    CentralBankStanceEvidence,
    EvidenceDisposition,
    PolicyDimension,
    StanceDirection,
    StanceEvidenceSpan,
    extract_central_bank_stance,
)


PREVIOUS = "a" * 64
CURRENT = "b" * 64


def change(side: str, index: int, text: str) -> DocumentTextChange:
    return DocumentTextChange.create(side, index, text)


def diff(*, added: tuple[DocumentTextChange, ...] = (), removed: tuple[DocumentTextChange, ...] = ()) -> OfficialDocumentDiff:
    return OfficialDocumentDiff("fed_fomc_statement", PREVIOUS, CURRENT, added, removed)


def test_added_hawkish_source_paragraph_is_supported_and_hash_bound() -> None:
    paragraph = "Inflation remains elevated."
    result = extract_central_bank_stance(diff(added=(change("added", 2, paragraph),)))
    assert result.research_only is True
    assert result.execution_authority is False
    assert result.ruleset_version == STANCE_RULESET_VERSION
    assert result.direction is StanceDirection.HAWKISH
    assert result.disposition is EvidenceDisposition.SUPPORTED
    assert result.evidence_quality_is_probability is False
    assert Decimal("0") < result.evidence_quality <= Decimal("1")
    assert len(result.spans) == 1
    span = result.spans[0]
    assert span.dimension is PolicyDimension.INFLATION
    assert span.lexical_direction is StanceDirection.HAWKISH
    assert span.effective_direction is StanceDirection.HAWKISH
    assert span.paragraph_sha256 == hashlib.sha256(paragraph.encode()).hexdigest()
    assert paragraph[span.start_char : span.end_char].lower() == "inflation remains elevated"
    assert span.qualified is False
    assert span.directional_weight == Decimal("0.8")


def test_removed_hawkish_and_removed_dovish_language_reverse_stance_delta() -> None:
    removed_hawkish = extract_central_bank_stance(
        diff(removed=(change("removed", 0, "The Committee sees upside risks to inflation."),))
    )
    assert removed_hawkish.direction is StanceDirection.DOVISH
    assert removed_hawkish.spans[0].lexical_direction is StanceDirection.HAWKISH
    assert removed_hawkish.spans[0].effective_direction is StanceDirection.DOVISH

    removed_dovish = extract_central_bank_stance(
        diff(removed=(change("removed", 0, "The Committee decided to lower the target range."),))
    )
    assert removed_dovish.direction is StanceDirection.HAWKISH
    assert removed_dovish.spans[0].effective_direction is StanceDirection.HAWKISH


def test_conditional_and_uncertain_only_evidence_is_directional_but_ambiguous() -> None:
    result = extract_central_bank_stance(
        diff(added=(change("added", 0, "If inflation remains elevated, policy may need to remain restrictive."),))
    )
    assert result.direction is StanceDirection.HAWKISH
    assert result.disposition is EvidenceDisposition.AMBIGUOUS
    assert len(result.spans) == 1
    span = result.spans[0]
    assert span.conditional is True
    assert span.uncertain is True
    assert span.negated is False
    assert span.directional_weight == Decimal("0.4")
    assert result.dimensions[0].disposition is EvidenceDisposition.AMBIGUOUS


def test_negated_match_is_retained_as_evidence_but_cannot_supply_direction() -> None:
    result = extract_central_bank_stance(
        diff(added=(change("added", 0, "It is not the case that inflation remains elevated."),))
    )
    assert result.direction is StanceDirection.NEUTRAL
    assert result.disposition is EvidenceDisposition.AMBIGUOUS
    assert len(result.spans) == 1
    assert result.spans[0].negated is True
    assert result.spans[0].directional_weight == Decimal("0")
    assert result.evidence_quality == Decimal("0.10")


def test_hawkish_and_dovish_supported_changes_remain_contradictory() -> None:
    result = extract_central_bank_stance(
        diff(
            added=(
                change("added", 0, "Inflation remains elevated."),
                change("added", 1, "The Committee decided to lower the target range."),
            )
        )
    )
    assert result.direction is StanceDirection.CONTRADICTORY
    assert result.disposition is EvidenceDisposition.CONTRADICTORY
    by_dimension = {item.dimension: item for item in result.dimensions}
    assert by_dimension[PolicyDimension.INFLATION].direction is StanceDirection.HAWKISH
    assert by_dimension[PolicyDimension.POLICY_RATE].direction is StanceDirection.DOVISH
    assert result.evidence_quality < Decimal("1")


def test_same_dimension_conflict_is_marked_contradictory_not_averaged() -> None:
    result = extract_central_bank_stance(
        diff(
            added=(
                change("added", 0, "The Committee discussed further tightening."),
                change("added", 1, "The Committee also discussed policy easing."),
            )
        )
    )
    assert result.direction is StanceDirection.CONTRADICTORY
    assert result.disposition is EvidenceDisposition.CONTRADICTORY
    rate = next(item for item in result.dimensions if item.dimension is PolicyDimension.POLICY_RATE)
    assert rate.direction is StanceDirection.CONTRADICTORY
    assert rate.hawkish_weight == Decimal("0.9")
    assert rate.dovish_weight == Decimal("0.85")


def test_no_supported_rule_abstains_instead_of_manufacturing_sentiment() -> None:
    result = extract_central_bank_stance(
        diff(added=(change("added", 0, "The meeting began at 10:00 a.m. and adjourned later."),))
    )
    assert result.direction is StanceDirection.NEUTRAL
    assert result.disposition is EvidenceDisposition.ABSTAINED
    assert result.spans == ()
    assert result.dimensions == ()
    assert result.evidence_quality == Decimal("0")
    assert result.abstention_reason is not None


def test_rule_matching_is_word_bounded_and_multiple_occurrences_have_distinct_evidence_ids() -> None:
    result = extract_central_bank_stance(
        diff(
            added=(
                change(
                    "added",
                    0,
                    "Inflation remains elevated; inflation remains elevated despite progress.",
                ),
            )
        )
    )
    assert len(result.spans) == 2
    assert len({item.evidence_id for item in result.spans}) == 2
    assert [item.start_char for item in result.spans] == sorted(item.start_char for item in result.spans)


def test_evidence_span_rejects_offset_hash_and_identity_tampering() -> None:
    result = extract_central_bank_stance(diff(added=(change("added", 0, "Inflation remains elevated."),)))
    span = result.spans[0]
    with pytest.raises(ValueError, match="offsets do not resolve"):
        StanceEvidenceSpan(
            evidence_id=span.evidence_id,
            change_side=span.change_side,
            paragraph_index=span.paragraph_index,
            paragraph_sha256=span.paragraph_sha256,
            paragraph_text=span.paragraph_text,
            rule_id=span.rule_id,
            phrase=span.phrase,
            start_char=span.start_char + 1,
            end_char=span.end_char,
            dimension=span.dimension,
            lexical_direction=span.lexical_direction,
            effective_direction=span.effective_direction,
            weight=span.weight,
            negated=span.negated,
            uncertain=span.uncertain,
            conditional=span.conditional,
        )
    with pytest.raises(ValueError, match="paragraph hash"):
        StanceEvidenceSpan(
            evidence_id=span.evidence_id,
            change_side=span.change_side,
            paragraph_index=span.paragraph_index,
            paragraph_sha256="0" * 64,
            paragraph_text=span.paragraph_text,
            rule_id=span.rule_id,
            phrase=span.phrase,
            start_char=span.start_char,
            end_char=span.end_char,
            dimension=span.dimension,
            lexical_direction=span.lexical_direction,
            effective_direction=span.effective_direction,
            weight=span.weight,
            negated=span.negated,
            uncertain=span.uncertain,
            conditional=span.conditional,
        )


def test_stance_artifact_cannot_claim_execution_or_probability() -> None:
    base = extract_central_bank_stance(diff(added=(change("added", 0, "Inflation remains elevated."),)))
    with pytest.raises(ValueError, match="research-only"):
        CentralBankStanceEvidence(
            research_only=False,
            execution_authority=False,
            ruleset_version=base.ruleset_version,
            family_id=base.family_id,
            previous_version_id=base.previous_version_id,
            current_version_id=base.current_version_id,
            direction=base.direction,
            disposition=base.disposition,
            evidence_quality=base.evidence_quality,
            evidence_quality_is_probability=False,
            dimensions=base.dimensions,
            spans=base.spans,
            abstention_reason=base.abstention_reason,
        )
    with pytest.raises(ValueError, match="probability"):
        CentralBankStanceEvidence(
            research_only=True,
            execution_authority=False,
            ruleset_version=base.ruleset_version,
            family_id=base.family_id,
            previous_version_id=base.previous_version_id,
            current_version_id=base.current_version_id,
            direction=base.direction,
            disposition=base.disposition,
            evidence_quality=base.evidence_quality,
            evidence_quality_is_probability=True,
            dimensions=base.dimensions,
            spans=base.spans,
            abstention_reason=base.abstention_reason,
        )
