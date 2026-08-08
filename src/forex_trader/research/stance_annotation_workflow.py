from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Iterable, Mapping

from forex_trader.intelligence.official_documents import (
    DocumentTextChange,
    OfficialDocumentVersion,
    compare_document_versions,
)
from forex_trader.research.central_bank_stance import EvidenceDisposition, PolicyDimension, StanceDirection
from forex_trader.research.stance_semantic_validation import (
    CentralBankSemanticLabel,
    DimensionSemanticLabel,
    official_document_diff_id,
)


ANNOTATION_PACKET_SCHEMA_VERSION = "central-bank-blinded-annotation-packet-v1"
ANNOTATION_BATCH_SCHEMA_VERSION = "central-bank-blinded-annotation-batch-v1"
REVIEWER_SUBMISSION_SCHEMA_VERSION = "central-bank-reviewer-submission-v1"
ADJUDICATION_SCHEMA_VERSION = "central-bank-adjudication-v1"
FINALIZATION_AUDIT_SCHEMA_VERSION = "central-bank-annotation-finalization-audit-v1"

_BATCH_KEYS = frozenset({"manifest", "packets"})
_MANIFEST_KEYS = frozenset(
    {
        "batch_id",
        "schema_version",
        "research_only",
        "execution_authority",
        "family_id",
        "annotation_policy_version",
        "as_of",
        "packet_count",
        "packet_ids",
    }
)
_PACKET_KEYS = frozenset(
    {
        "packet_id",
        "schema_version",
        "research_only",
        "execution_authority",
        "annotation_policy_version",
        "family_id",
        "source_id",
        "institution",
        "document_type",
        "currency",
        "previous_version_id",
        "current_version_id",
        "previous_document_url",
        "current_document_url",
        "previous_published_at",
        "current_published_at",
        "previous_available_at",
        "current_available_at",
        "previous_text_sha256",
        "current_text_sha256",
        "previous_text",
        "current_text",
        "diff_id",
        "added",
        "removed",
    }
)
_SUBMISSION_KEYS = frozenset(
    {
        "submission_id",
        "schema_version",
        "research_only",
        "execution_authority",
        "packet_id",
        "annotation_policy_version",
        "reviewer_id",
        "submitted_at",
        "direction",
        "disposition",
        "dimensions",
    }
)
_ADJUDICATION_KEYS = frozenset(
    {
        "adjudication_id",
        "schema_version",
        "research_only",
        "execution_authority",
        "packet_id",
        "annotation_policy_version",
        "source_submission_ids",
        "adjudicator_id",
        "adjudicated_at",
        "direction",
        "disposition",
        "dimensions",
    }
)
_CHANGE_KEYS = frozenset({"side", "paragraph_index", "text", "text_sha256"})
_DIMENSION_KEYS = frozenset({"dimension", "direction", "disposition"})


@dataclass(frozen=True, slots=True)
class BlindedAnnotationPacket:
    packet_id: str
    schema_version: str
    research_only: bool
    execution_authority: bool
    annotation_policy_version: str
    family_id: str
    source_id: str
    institution: str
    document_type: str
    currency: str
    previous_version_id: str
    current_version_id: str
    previous_document_url: str
    current_document_url: str
    previous_published_at: datetime
    current_published_at: datetime
    previous_available_at: datetime
    current_available_at: datetime
    previous_text_sha256: str
    current_text_sha256: str
    previous_text: str
    current_text: str
    diff_id: str
    added: tuple[DocumentTextChange, ...]
    removed: tuple[DocumentTextChange, ...]

    def __post_init__(self) -> None:
        if self.schema_version != ANNOTATION_PACKET_SCHEMA_VERSION:
            raise ValueError("unsupported blinded annotation packet schema")
        if self.research_only is not True or self.execution_authority is not False:
            raise ValueError("annotation packets must remain research-only with no execution authority")
        required = (
            self.annotation_policy_version,
            self.family_id,
            self.source_id,
            self.institution,
            self.document_type,
            self.currency,
            self.previous_document_url,
            self.current_document_url,
            self.previous_text,
            self.current_text,
        )
        if any(not item.strip() for item in required):
            raise ValueError("annotation packet identity and source text fields are required")
        for value, name in (
            (self.packet_id, "packet_id"),
            (self.previous_version_id, "previous_version_id"),
            (self.current_version_id, "current_version_id"),
            (self.previous_text_sha256, "previous_text_sha256"),
            (self.current_text_sha256, "current_text_sha256"),
            (self.diff_id, "diff_id"),
        ):
            _require_sha256(value, name)
        if self.previous_version_id == self.current_version_id:
            raise ValueError("annotation packet source versions must differ")
        for instant in (
            self.previous_published_at,
            self.current_published_at,
            self.previous_available_at,
            self.current_available_at,
        ):
            if instant.tzinfo is None:
                raise ValueError("annotation packet source timestamps must be timezone-aware")
        if self.previous_available_at >= self.current_available_at:
            raise ValueError("annotation packet source lineage must be chronologically ordered")
        if hashlib.sha256(self.previous_text.encode()).hexdigest() != self.previous_text_sha256:
            raise ValueError("annotation packet previous text hash does not match text")
        if hashlib.sha256(self.current_text.encode()).hexdigest() != self.current_text_sha256:
            raise ValueError("annotation packet current text hash does not match text")
        if any(item.side != "added" for item in self.added) or any(item.side != "removed" for item in self.removed):
            raise ValueError("annotation packet diff changes must preserve their declared side")
        if self.packet_id != _packet_id_values(
            annotation_policy_version=self.annotation_policy_version,
            family_id=self.family_id,
            source_id=self.source_id,
            institution=self.institution,
            document_type=self.document_type,
            currency=self.currency,
            previous_version_id=self.previous_version_id,
            current_version_id=self.current_version_id,
            previous_document_url=self.previous_document_url,
            current_document_url=self.current_document_url,
            previous_published_at=self.previous_published_at,
            current_published_at=self.current_published_at,
            previous_available_at=self.previous_available_at,
            current_available_at=self.current_available_at,
            previous_text_sha256=self.previous_text_sha256,
            current_text_sha256=self.current_text_sha256,
            previous_text=self.previous_text,
            current_text=self.current_text,
            diff_id=self.diff_id,
            added=self.added,
            removed=self.removed,
        ):
            raise ValueError("annotation packet ID does not match its source-only payload")

    @classmethod
    def create(
        cls,
        previous: OfficialDocumentVersion,
        current: OfficialDocumentVersion,
        *,
        annotation_policy_version: str,
    ) -> BlindedAnnotationPacket:
        policy = annotation_policy_version.strip()
        if not policy:
            raise ValueError("annotation policy version is required")
        _validate_source_pair(previous, current)
        diff = compare_document_versions(previous, current)
        packet_id = _packet_id_values(
            annotation_policy_version=policy,
            family_id=current.family_id,
            source_id=current.source_id,
            institution=current.institution,
            document_type=current.document_type,
            currency=current.currency.upper(),
            previous_version_id=previous.version_id,
            current_version_id=current.version_id,
            previous_document_url=previous.document_url,
            current_document_url=current.document_url,
            previous_published_at=previous.published_at,
            current_published_at=current.published_at,
            previous_available_at=previous.available_at,
            current_available_at=current.available_at,
            previous_text_sha256=previous.text_sha256,
            current_text_sha256=current.text_sha256,
            previous_text=previous.text,
            current_text=current.text,
            diff_id=official_document_diff_id(diff),
            added=diff.added,
            removed=diff.removed,
        )
        return cls(
            packet_id=packet_id,
            schema_version=ANNOTATION_PACKET_SCHEMA_VERSION,
            research_only=True,
            execution_authority=False,
            annotation_policy_version=policy,
            family_id=current.family_id,
            source_id=current.source_id,
            institution=current.institution,
            document_type=current.document_type,
            currency=current.currency.upper(),
            previous_version_id=previous.version_id,
            current_version_id=current.version_id,
            previous_document_url=previous.document_url,
            current_document_url=current.document_url,
            previous_published_at=previous.published_at,
            current_published_at=current.published_at,
            previous_available_at=previous.available_at,
            current_available_at=current.available_at,
            previous_text_sha256=previous.text_sha256,
            current_text_sha256=current.text_sha256,
            previous_text=previous.text,
            current_text=current.text,
            diff_id=official_document_diff_id(diff),
            added=diff.added,
            removed=diff.removed,
        )


@dataclass(frozen=True, slots=True)
class AnnotationBatchManifest:
    batch_id: str
    schema_version: str
    research_only: bool
    execution_authority: bool
    family_id: str
    annotation_policy_version: str
    as_of: datetime
    packet_count: int
    packet_ids: tuple[str, ...]

    def __post_init__(self) -> None:
        if self.schema_version != ANNOTATION_BATCH_SCHEMA_VERSION:
            raise ValueError("unsupported annotation batch schema")
        if self.research_only is not True or self.execution_authority is not False:
            raise ValueError("annotation batch must remain research-only")
        if not self.family_id.strip() or not self.annotation_policy_version.strip():
            raise ValueError("annotation batch family/policy identity is required")
        if self.as_of.tzinfo is None:
            raise ValueError("annotation batch as_of must be timezone-aware")
        if self.packet_count < 1 or self.packet_count != len(self.packet_ids):
            raise ValueError("annotation batch packet denominator is inconsistent")
        if len(set(self.packet_ids)) != len(self.packet_ids):
            raise ValueError("annotation batch packet IDs must be unique")
        for packet_id in self.packet_ids:
            _require_sha256(packet_id, "packet_id")
        if self.batch_id != _batch_id(
            family_id=self.family_id,
            annotation_policy_version=self.annotation_policy_version,
            as_of=self.as_of,
            packet_ids=self.packet_ids,
        ):
            raise ValueError("annotation batch ID does not match its frozen packet manifest")


@dataclass(frozen=True, slots=True)
class AnnotationBatch:
    manifest: AnnotationBatchManifest
    packets: tuple[BlindedAnnotationPacket, ...]

    def __post_init__(self) -> None:
        if len(self.packets) != self.manifest.packet_count:
            raise ValueError("annotation batch packets do not match manifest count")
        if tuple(item.packet_id for item in self.packets) != self.manifest.packet_ids:
            raise ValueError("annotation batch packet ordering does not match manifest")
        if any(item.family_id != self.manifest.family_id for item in self.packets):
            raise ValueError("annotation batch packets must share the manifest family")
        if any(item.annotation_policy_version != self.manifest.annotation_policy_version for item in self.packets):
            raise ValueError("annotation batch packets must share the manifest annotation policy")
        if any(item.current_available_at > self.manifest.as_of for item in self.packets):
            raise ValueError("annotation batch cannot contain source evidence after its frozen as_of")


@dataclass(frozen=True, slots=True)
class ReviewerSubmission:
    submission_id: str
    schema_version: str
    research_only: bool
    execution_authority: bool
    packet_id: str
    annotation_policy_version: str
    reviewer_id: str
    submitted_at: datetime
    direction: StanceDirection
    disposition: EvidenceDisposition
    dimensions: tuple[DimensionSemanticLabel, ...]

    def __post_init__(self) -> None:
        if self.schema_version != REVIEWER_SUBMISSION_SCHEMA_VERSION:
            raise ValueError("unsupported reviewer submission schema")
        if self.research_only is not True or self.execution_authority is not False:
            raise ValueError("reviewer submissions must remain research-only")
        _require_sha256(self.packet_id, "reviewer submission packet_id")
        if not self.annotation_policy_version.strip() or not self.reviewer_id.strip():
            raise ValueError("reviewer submission policy and pseudonymous reviewer ID are required")
        if self.reviewer_id != self.reviewer_id.strip():
            raise ValueError("reviewer ID must be normalized")
        if self.submitted_at.tzinfo is None:
            raise ValueError("reviewer submission timestamp must be timezone-aware")
        _validate_truth(self.direction, self.disposition, "reviewer submission")
        _validate_dimensions(self.dimensions, "reviewer submission")
        if self.submission_id != _submission_id_values(
            packet_id=self.packet_id,
            annotation_policy_version=self.annotation_policy_version,
            reviewer_id=self.reviewer_id,
            submitted_at=self.submitted_at,
            direction=self.direction,
            disposition=self.disposition,
            dimensions=self.dimensions,
        ):
            raise ValueError("reviewer submission ID does not match its immutable review payload")

    @classmethod
    def create(
        cls,
        packet: BlindedAnnotationPacket,
        *,
        reviewer_id: str,
        submitted_at: datetime,
        direction: StanceDirection,
        disposition: EvidenceDisposition,
        dimensions: Iterable[DimensionSemanticLabel] = (),
    ) -> ReviewerSubmission:
        normalized_dimensions = tuple(sorted(dimensions, key=lambda item: item.dimension.value))
        normalized_reviewer = reviewer_id.strip()
        submission_id = _submission_id_values(
            packet_id=packet.packet_id,
            annotation_policy_version=packet.annotation_policy_version,
            reviewer_id=normalized_reviewer,
            submitted_at=submitted_at,
            direction=direction,
            disposition=disposition,
            dimensions=normalized_dimensions,
        )
        return cls(
            submission_id=submission_id,
            schema_version=REVIEWER_SUBMISSION_SCHEMA_VERSION,
            research_only=True,
            execution_authority=False,
            packet_id=packet.packet_id,
            annotation_policy_version=packet.annotation_policy_version,
            reviewer_id=normalized_reviewer,
            submitted_at=submitted_at,
            direction=direction,
            disposition=disposition,
            dimensions=normalized_dimensions,
        )


@dataclass(frozen=True, slots=True)
class AdjudicationRecord:
    adjudication_id: str
    schema_version: str
    research_only: bool
    execution_authority: bool
    packet_id: str
    annotation_policy_version: str
    source_submission_ids: tuple[str, ...]
    adjudicator_id: str
    adjudicated_at: datetime
    direction: StanceDirection
    disposition: EvidenceDisposition
    dimensions: tuple[DimensionSemanticLabel, ...]

    def __post_init__(self) -> None:
        if self.schema_version != ADJUDICATION_SCHEMA_VERSION:
            raise ValueError("unsupported adjudication schema")
        if self.research_only is not True or self.execution_authority is not False:
            raise ValueError("adjudication records must remain research-only")
        _require_sha256(self.packet_id, "adjudication packet_id")
        if not self.annotation_policy_version.strip() or not self.adjudicator_id.strip():
            raise ValueError("adjudication policy and adjudicator ID are required")
        if self.adjudicator_id != self.adjudicator_id.strip():
            raise ValueError("adjudicator ID must be normalized")
        if len(self.source_submission_ids) < 2:
            raise ValueError("adjudication requires at least two reviewer submissions")
        if tuple(sorted(set(self.source_submission_ids))) != self.source_submission_ids:
            raise ValueError("adjudication source submission IDs must be sorted and unique")
        for submission_id in self.source_submission_ids:
            _require_sha256(submission_id, "adjudication source_submission_id")
        if self.adjudicated_at.tzinfo is None:
            raise ValueError("adjudication timestamp must be timezone-aware")
        _validate_truth(self.direction, self.disposition, "adjudication")
        _validate_dimensions(self.dimensions, "adjudication")
        if self.adjudication_id != _adjudication_id_values(
            packet_id=self.packet_id,
            annotation_policy_version=self.annotation_policy_version,
            source_submission_ids=self.source_submission_ids,
            adjudicator_id=self.adjudicator_id,
            adjudicated_at=self.adjudicated_at,
            direction=self.direction,
            disposition=self.disposition,
            dimensions=self.dimensions,
        ):
            raise ValueError("adjudication ID does not match its immutable payload")

    @classmethod
    def create(
        cls,
        packet: BlindedAnnotationPacket,
        submissions: Iterable[ReviewerSubmission],
        *,
        adjudicator_id: str,
        adjudicated_at: datetime,
        direction: StanceDirection,
        disposition: EvidenceDisposition,
        dimensions: Iterable[DimensionSemanticLabel] = (),
    ) -> AdjudicationRecord:
        source = tuple(submissions)
        _validate_submission_group(packet, source, require_two=True)
        reviewer_ids = {item.reviewer_id for item in source}
        normalized_adjudicator = adjudicator_id.strip()
        if normalized_adjudicator in reviewer_ids:
            raise ValueError("adjudicator must be independent from source reviewers")
        if any(item.submitted_at > adjudicated_at for item in source):
            raise ValueError("adjudication cannot precede a source reviewer submission")
        source_ids = tuple(sorted(item.submission_id for item in source))
        normalized_dimensions = tuple(sorted(dimensions, key=lambda item: item.dimension.value))
        adjudication_id = _adjudication_id_values(
            packet_id=packet.packet_id,
            annotation_policy_version=packet.annotation_policy_version,
            source_submission_ids=source_ids,
            adjudicator_id=normalized_adjudicator,
            adjudicated_at=adjudicated_at,
            direction=direction,
            disposition=disposition,
            dimensions=normalized_dimensions,
        )
        return cls(
            adjudication_id=adjudication_id,
            schema_version=ADJUDICATION_SCHEMA_VERSION,
            research_only=True,
            execution_authority=False,
            packet_id=packet.packet_id,
            annotation_policy_version=packet.annotation_policy_version,
            source_submission_ids=source_ids,
            adjudicator_id=normalized_adjudicator,
            adjudicated_at=adjudicated_at,
            direction=direction,
            disposition=disposition,
            dimensions=normalized_dimensions,
        )


@dataclass(frozen=True, slots=True)
class FinalizationAudit:
    audit_id: str
    schema_version: str
    research_only: bool
    execution_authority: bool
    batch_id: str
    packet_id: str
    adjudication_id: str
    semantic_label_id: str
    source_submission_ids: tuple[str, ...]
    reviewer_ids: tuple[str, ...]
    reviewer_overall_agreement: bool
    reviewer_dimension_agreement: bool

    def __post_init__(self) -> None:
        if self.schema_version != FINALIZATION_AUDIT_SCHEMA_VERSION:
            raise ValueError("unsupported annotation finalization audit schema")
        if self.research_only is not True or self.execution_authority is not False:
            raise ValueError("annotation finalization audits must remain research-only")
        for value, name in (
            (self.batch_id, "batch_id"),
            (self.packet_id, "packet_id"),
            (self.adjudication_id, "adjudication_id"),
            (self.semantic_label_id, "semantic_label_id"),
        ):
            _require_sha256(value, name)
        if len(self.source_submission_ids) < 2:
            raise ValueError("annotation finalization audit requires source submissions")
        if tuple(sorted(set(self.source_submission_ids))) != self.source_submission_ids:
            raise ValueError("annotation audit submission IDs must be sorted and unique")
        if tuple(sorted(set(self.reviewer_ids))) != self.reviewer_ids:
            raise ValueError("annotation audit reviewer IDs must be sorted and unique")
        if len(self.source_submission_ids) != len(self.reviewer_ids):
            raise ValueError("annotation audit reviewer/submission denominators must match")
        if self.audit_id != _audit_id_values(
            batch_id=self.batch_id,
            packet_id=self.packet_id,
            adjudication_id=self.adjudication_id,
            semantic_label_id=self.semantic_label_id,
            source_submission_ids=self.source_submission_ids,
            reviewer_ids=self.reviewer_ids,
            reviewer_overall_agreement=self.reviewer_overall_agreement,
            reviewer_dimension_agreement=self.reviewer_dimension_agreement,
        ):
            raise ValueError("annotation finalization audit ID does not match its payload")


@dataclass(frozen=True, slots=True)
class FinalizedAnnotation:
    semantic_label: CentralBankSemanticLabel
    audit: FinalizationAudit

    def __post_init__(self) -> None:
        if self.semantic_label.label_id != self.audit.semantic_label_id:
            raise ValueError("finalized annotation label does not match audit")


def build_blinded_annotation_batch(
    versions: Iterable[OfficialDocumentVersion],
    *,
    annotation_policy_version: str,
    as_of: datetime,
) -> AnnotationBatch:
    if as_of.tzinfo is None:
        raise ValueError("annotation batch as_of must be timezone-aware")
    policy = annotation_policy_version.strip()
    if not policy:
        raise ValueError("annotation policy version is required")
    source = tuple(versions)
    if len(source) < 2:
        raise ValueError("annotation batch requires at least two official document versions")
    if len({item.version_id for item in source}) != len(source):
        raise ValueError("annotation batch source versions cannot repeat")
    family_ids = {item.family_id for item in source}
    if len(family_ids) != 1:
        raise ValueError("annotation batch must contain exactly one explicit document family")
    family_id = next(iter(family_ids))
    by_id = {item.version_id: item for item in source}
    eligible = tuple(
        sorted(
            (item for item in source if item.predecessor_version_id is not None and item.available_at <= as_of),
            key=lambda item: (item.available_at, item.version_id),
        )
    )
    if not eligible:
        raise ValueError("annotation batch has no comparable document versions by its frozen as_of")
    packets: list[BlindedAnnotationPacket] = []
    for current in eligible:
        predecessor_id = current.predecessor_version_id
        if predecessor_id is None:
            raise ValueError("annotation batch comparable source unexpectedly lacks predecessor")
        previous = by_id.get(predecessor_id)
        if previous is None:
            raise ValueError("annotation batch source corpus is missing an explicit predecessor")
        packets.append(
            BlindedAnnotationPacket.create(
                previous,
                current,
                annotation_policy_version=policy,
            )
        )
    packet_tuple = tuple(packets)
    packet_ids = tuple(item.packet_id for item in packet_tuple)
    manifest = AnnotationBatchManifest(
        batch_id=_batch_id(
            family_id=family_id,
            annotation_policy_version=policy,
            as_of=as_of,
            packet_ids=packet_ids,
        ),
        schema_version=ANNOTATION_BATCH_SCHEMA_VERSION,
        research_only=True,
        execution_authority=False,
        family_id=family_id,
        annotation_policy_version=policy,
        as_of=as_of,
        packet_count=len(packet_tuple),
        packet_ids=packet_ids,
    )
    return AnnotationBatch(manifest=manifest, packets=packet_tuple)


def finalize_annotation_batch(
    batch: AnnotationBatch,
    submissions: Iterable[ReviewerSubmission],
    adjudications: Iterable[AdjudicationRecord],
    versions: Iterable[OfficialDocumentVersion],
) -> tuple[FinalizedAnnotation, ...]:
    version_records = tuple(versions)
    rebuilt = build_blinded_annotation_batch(
        version_records,
        annotation_policy_version=batch.manifest.annotation_policy_version,
        as_of=batch.manifest.as_of,
    )
    if rebuilt != batch:
        raise ValueError("annotation batch does not match reconstructed frozen source evidence")
    packet_by_id = {item.packet_id: item for item in batch.packets}
    version_by_id = {item.version_id: item for item in version_records}
    submission_records = tuple(submissions)
    adjudication_records = tuple(adjudications)
    if len({item.submission_id for item in submission_records}) != len(submission_records):
        raise ValueError("annotation finalization cannot contain duplicate reviewer submission IDs")
    if len({item.adjudication_id for item in adjudication_records}) != len(adjudication_records):
        raise ValueError("annotation finalization cannot contain duplicate adjudication IDs")
    submissions_by_packet: dict[str, list[ReviewerSubmission]] = {}
    for submission in submission_records:
        if submission.packet_id not in packet_by_id:
            raise ValueError("reviewer submission references a packet outside the frozen annotation batch")
        submissions_by_packet.setdefault(submission.packet_id, []).append(submission)
    adjudications_by_packet: dict[str, list[AdjudicationRecord]] = {}
    for adjudication in adjudication_records:
        if adjudication.packet_id not in packet_by_id:
            raise ValueError("adjudication references a packet outside the frozen annotation batch")
        adjudications_by_packet.setdefault(adjudication.packet_id, []).append(adjudication)

    finalized: list[FinalizedAnnotation] = []
    for packet in batch.packets:
        source_submissions = tuple(submissions_by_packet.get(packet.packet_id, ()))
        _validate_submission_group(packet, source_submissions, require_two=True)
        packet_adjudications = tuple(adjudications_by_packet.get(packet.packet_id, ()))
        if len(packet_adjudications) != 1:
            raise ValueError("every annotation packet requires exactly one adjudication")
        adjudication = packet_adjudications[0]
        _validate_adjudication(packet, source_submissions, adjudication)
        previous = version_by_id.get(packet.previous_version_id)
        current = version_by_id.get(packet.current_version_id)
        if previous is None or current is None:
            raise ValueError("annotation packet source versions are missing during finalization")
        diff = compare_document_versions(previous, current)
        if official_document_diff_id(diff) != packet.diff_id:
            raise ValueError("annotation packet diff changed before semantic-label finalization")
        reviewer_ids = tuple(sorted(item.reviewer_id for item in source_submissions))
        semantic_label = CentralBankSemanticLabel.create(
            diff,
            annotation_policy_version=packet.annotation_policy_version,
            annotator_ids=reviewer_ids,
            adjudicated=True,
            adjudicator_id=adjudication.adjudicator_id,
            labeled_at=adjudication.adjudicated_at,
            direction=adjudication.direction,
            disposition=adjudication.disposition,
            dimensions=adjudication.dimensions,
        )
        submission_ids = tuple(sorted(item.submission_id for item in source_submissions))
        overall_agreement = len({(item.direction, item.disposition) for item in source_submissions}) == 1
        dimension_agreement = len({item.dimensions for item in source_submissions}) == 1
        audit = FinalizationAudit(
            audit_id=_audit_id_values(
                batch_id=batch.manifest.batch_id,
                packet_id=packet.packet_id,
                adjudication_id=adjudication.adjudication_id,
                semantic_label_id=semantic_label.label_id,
                source_submission_ids=submission_ids,
                reviewer_ids=reviewer_ids,
                reviewer_overall_agreement=overall_agreement,
                reviewer_dimension_agreement=dimension_agreement,
            ),
            schema_version=FINALIZATION_AUDIT_SCHEMA_VERSION,
            research_only=True,
            execution_authority=False,
            batch_id=batch.manifest.batch_id,
            packet_id=packet.packet_id,
            adjudication_id=adjudication.adjudication_id,
            semantic_label_id=semantic_label.label_id,
            source_submission_ids=submission_ids,
            reviewer_ids=reviewer_ids,
            reviewer_overall_agreement=overall_agreement,
            reviewer_dimension_agreement=dimension_agreement,
        )
        finalized.append(FinalizedAnnotation(semantic_label=semantic_label, audit=audit))
    if len(finalized) != batch.manifest.packet_count:
        raise ValueError("annotation finalization did not account for the full frozen batch")
    return tuple(finalized)


def annotation_batch_to_dict(batch: AnnotationBatch) -> dict[str, object]:
    return {
        "manifest": {
            "batch_id": batch.manifest.batch_id,
            "schema_version": batch.manifest.schema_version,
            "research_only": batch.manifest.research_only,
            "execution_authority": batch.manifest.execution_authority,
            "family_id": batch.manifest.family_id,
            "annotation_policy_version": batch.manifest.annotation_policy_version,
            "as_of": batch.manifest.as_of.isoformat(),
            "packet_count": batch.manifest.packet_count,
            "packet_ids": list(batch.manifest.packet_ids),
        },
        "packets": [_packet_to_dict(item) for item in batch.packets],
    }


def reviewer_submission_to_dict(item: ReviewerSubmission) -> dict[str, object]:
    return {
        "submission_id": item.submission_id,
        "schema_version": item.schema_version,
        "research_only": item.research_only,
        "execution_authority": item.execution_authority,
        "packet_id": item.packet_id,
        "annotation_policy_version": item.annotation_policy_version,
        "reviewer_id": item.reviewer_id,
        "submitted_at": item.submitted_at.isoformat(),
        "direction": item.direction.value,
        "disposition": item.disposition.value,
        "dimensions": [_dimension_to_dict(value) for value in item.dimensions],
    }


def adjudication_to_dict(item: AdjudicationRecord) -> dict[str, object]:
    return {
        "adjudication_id": item.adjudication_id,
        "schema_version": item.schema_version,
        "research_only": item.research_only,
        "execution_authority": item.execution_authority,
        "packet_id": item.packet_id,
        "annotation_policy_version": item.annotation_policy_version,
        "source_submission_ids": list(item.source_submission_ids),
        "adjudicator_id": item.adjudicator_id,
        "adjudicated_at": item.adjudicated_at.isoformat(),
        "direction": item.direction.value,
        "disposition": item.disposition.value,
        "dimensions": [_dimension_to_dict(value) for value in item.dimensions],
    }


def semantic_label_to_dict(item: CentralBankSemanticLabel) -> dict[str, object]:
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
        "dimensions": [_dimension_to_dict(value) for value in item.dimensions],
    }


def finalization_audit_to_dict(item: FinalizationAudit) -> dict[str, object]:
    return {
        "audit_id": item.audit_id,
        "schema_version": item.schema_version,
        "research_only": item.research_only,
        "execution_authority": item.execution_authority,
        "batch_id": item.batch_id,
        "packet_id": item.packet_id,
        "adjudication_id": item.adjudication_id,
        "semantic_label_id": item.semantic_label_id,
        "source_submission_ids": list(item.source_submission_ids),
        "reviewer_ids": list(item.reviewer_ids),
        "reviewer_overall_agreement": item.reviewer_overall_agreement,
        "reviewer_dimension_agreement": item.reviewer_dimension_agreement,
    }


def load_annotation_batch(path: str | Path) -> AnnotationBatch:
    raw = _load_json_object(path, "annotation batch")
    _require_exact_keys(raw, _BATCH_KEYS, "annotation batch")
    manifest_raw = _require_mapping(raw.get("manifest"), "annotation batch manifest")
    _require_exact_keys(manifest_raw, _MANIFEST_KEYS, "annotation batch manifest")
    packets_raw = _require_list(raw.get("packets"), "annotation batch packets")
    manifest = AnnotationBatchManifest(
        batch_id=_require_str(manifest_raw.get("batch_id"), "batch_id"),
        schema_version=_require_str(manifest_raw.get("schema_version"), "schema_version"),
        research_only=_require_bool(manifest_raw.get("research_only"), "research_only"),
        execution_authority=_require_bool(manifest_raw.get("execution_authority"), "execution_authority"),
        family_id=_require_str(manifest_raw.get("family_id"), "family_id"),
        annotation_policy_version=_require_str(manifest_raw.get("annotation_policy_version"), "annotation_policy_version"),
        as_of=_require_datetime(manifest_raw.get("as_of"), "as_of"),
        packet_count=_require_int(manifest_raw.get("packet_count"), "packet_count"),
        packet_ids=_require_str_tuple(manifest_raw.get("packet_ids"), "packet_ids"),
    )
    packets: list[BlindedAnnotationPacket] = []
    for item in packets_raw:
        mapping = _require_mapping(item, "annotation packet")
        _require_exact_keys(mapping, _PACKET_KEYS, "annotation packet")
        packets.append(_packet_from_mapping(mapping))
    return AnnotationBatch(manifest=manifest, packets=tuple(packets))


def load_reviewer_submissions(path: str | Path) -> tuple[ReviewerSubmission, ...]:
    result: list[ReviewerSubmission] = []
    for item in _load_jsonl_objects(path, "reviewer submission"):
        _require_exact_keys(item, _SUBMISSION_KEYS, "reviewer submission")
        result.append(_submission_from_mapping(item))
    return tuple(result)


def load_adjudications(path: str | Path) -> tuple[AdjudicationRecord, ...]:
    result: list[AdjudicationRecord] = []
    for item in _load_jsonl_objects(path, "adjudication"):
        _require_exact_keys(item, _ADJUDICATION_KEYS, "adjudication")
        result.append(_adjudication_from_mapping(item))
    return tuple(result)


def _packet_to_dict(item: BlindedAnnotationPacket) -> dict[str, object]:
    return {
        "packet_id": item.packet_id,
        "schema_version": item.schema_version,
        "research_only": item.research_only,
        "execution_authority": item.execution_authority,
        "annotation_policy_version": item.annotation_policy_version,
        "family_id": item.family_id,
        "source_id": item.source_id,
        "institution": item.institution,
        "document_type": item.document_type,
        "currency": item.currency,
        "previous_version_id": item.previous_version_id,
        "current_version_id": item.current_version_id,
        "previous_document_url": item.previous_document_url,
        "current_document_url": item.current_document_url,
        "previous_published_at": item.previous_published_at.isoformat(),
        "current_published_at": item.current_published_at.isoformat(),
        "previous_available_at": item.previous_available_at.isoformat(),
        "current_available_at": item.current_available_at.isoformat(),
        "previous_text_sha256": item.previous_text_sha256,
        "current_text_sha256": item.current_text_sha256,
        "previous_text": item.previous_text,
        "current_text": item.current_text,
        "diff_id": item.diff_id,
        "added": [_change_to_dict(value) for value in item.added],
        "removed": [_change_to_dict(value) for value in item.removed],
    }


def _packet_from_mapping(raw: Mapping[str, object]) -> BlindedAnnotationPacket:
    return BlindedAnnotationPacket(
        packet_id=_require_str(raw.get("packet_id"), "packet_id"),
        schema_version=_require_str(raw.get("schema_version"), "schema_version"),
        research_only=_require_bool(raw.get("research_only"), "research_only"),
        execution_authority=_require_bool(raw.get("execution_authority"), "execution_authority"),
        annotation_policy_version=_require_str(raw.get("annotation_policy_version"), "annotation_policy_version"),
        family_id=_require_str(raw.get("family_id"), "family_id"),
        source_id=_require_str(raw.get("source_id"), "source_id"),
        institution=_require_str(raw.get("institution"), "institution"),
        document_type=_require_str(raw.get("document_type"), "document_type"),
        currency=_require_str(raw.get("currency"), "currency"),
        previous_version_id=_require_str(raw.get("previous_version_id"), "previous_version_id"),
        current_version_id=_require_str(raw.get("current_version_id"), "current_version_id"),
        previous_document_url=_require_str(raw.get("previous_document_url"), "previous_document_url"),
        current_document_url=_require_str(raw.get("current_document_url"), "current_document_url"),
        previous_published_at=_require_datetime(raw.get("previous_published_at"), "previous_published_at"),
        current_published_at=_require_datetime(raw.get("current_published_at"), "current_published_at"),
        previous_available_at=_require_datetime(raw.get("previous_available_at"), "previous_available_at"),
        current_available_at=_require_datetime(raw.get("current_available_at"), "current_available_at"),
        previous_text_sha256=_require_str(raw.get("previous_text_sha256"), "previous_text_sha256"),
        current_text_sha256=_require_str(raw.get("current_text_sha256"), "current_text_sha256"),
        previous_text=_require_str(raw.get("previous_text"), "previous_text"),
        current_text=_require_str(raw.get("current_text"), "current_text"),
        diff_id=_require_str(raw.get("diff_id"), "diff_id"),
        added=_changes_from_value(raw.get("added"), "added"),
        removed=_changes_from_value(raw.get("removed"), "removed"),
    )


def _submission_from_mapping(raw: Mapping[str, object]) -> ReviewerSubmission:
    return ReviewerSubmission(
        submission_id=_require_str(raw.get("submission_id"), "submission_id"),
        schema_version=_require_str(raw.get("schema_version"), "schema_version"),
        research_only=_require_bool(raw.get("research_only"), "research_only"),
        execution_authority=_require_bool(raw.get("execution_authority"), "execution_authority"),
        packet_id=_require_str(raw.get("packet_id"), "packet_id"),
        annotation_policy_version=_require_str(raw.get("annotation_policy_version"), "annotation_policy_version"),
        reviewer_id=_require_str(raw.get("reviewer_id"), "reviewer_id"),
        submitted_at=_require_datetime(raw.get("submitted_at"), "submitted_at"),
        direction=StanceDirection(_require_str(raw.get("direction"), "direction")),
        disposition=EvidenceDisposition(_require_str(raw.get("disposition"), "disposition")),
        dimensions=_dimensions_from_value(raw.get("dimensions")),
    )


def _adjudication_from_mapping(raw: Mapping[str, object]) -> AdjudicationRecord:
    return AdjudicationRecord(
        adjudication_id=_require_str(raw.get("adjudication_id"), "adjudication_id"),
        schema_version=_require_str(raw.get("schema_version"), "schema_version"),
        research_only=_require_bool(raw.get("research_only"), "research_only"),
        execution_authority=_require_bool(raw.get("execution_authority"), "execution_authority"),
        packet_id=_require_str(raw.get("packet_id"), "packet_id"),
        annotation_policy_version=_require_str(raw.get("annotation_policy_version"), "annotation_policy_version"),
        source_submission_ids=_require_str_tuple(raw.get("source_submission_ids"), "source_submission_ids"),
        adjudicator_id=_require_str(raw.get("adjudicator_id"), "adjudicator_id"),
        adjudicated_at=_require_datetime(raw.get("adjudicated_at"), "adjudicated_at"),
        direction=StanceDirection(_require_str(raw.get("direction"), "direction")),
        disposition=EvidenceDisposition(_require_str(raw.get("disposition"), "disposition")),
        dimensions=_dimensions_from_value(raw.get("dimensions")),
    )


def _validate_source_pair(previous: OfficialDocumentVersion, current: OfficialDocumentVersion) -> None:
    fields = ("family_id", "source_id", "institution", "document_type", "currency")
    if any(getattr(previous, field) != getattr(current, field) for field in fields):
        raise ValueError("annotation packet source pair changes explicit family metadata")
    if current.predecessor_version_id != previous.version_id:
        raise ValueError("annotation packet current source does not reference the supplied predecessor")
    if previous.available_at >= current.available_at:
        raise ValueError("annotation packet source pair must be chronologically ordered")


def _validate_submission_group(
    packet: BlindedAnnotationPacket,
    submissions: tuple[ReviewerSubmission, ...],
    *,
    require_two: bool,
) -> None:
    if require_two and len(submissions) < 2:
        raise ValueError("every annotation packet requires at least two independent reviewer submissions")
    if len({item.submission_id for item in submissions}) != len(submissions):
        raise ValueError("annotation packet reviewer submissions cannot repeat")
    reviewer_ids = tuple(item.reviewer_id for item in submissions)
    if len(set(reviewer_ids)) != len(reviewer_ids):
        raise ValueError("annotation packet reviewers must be independent pseudonymous reviewers")
    for submission in submissions:
        if submission.packet_id != packet.packet_id:
            raise ValueError("reviewer submission does not match annotation packet")
        if submission.annotation_policy_version != packet.annotation_policy_version:
            raise ValueError("reviewer submission annotation policy does not match packet")


def _validate_adjudication(
    packet: BlindedAnnotationPacket,
    submissions: tuple[ReviewerSubmission, ...],
    adjudication: AdjudicationRecord,
) -> None:
    if adjudication.packet_id != packet.packet_id:
        raise ValueError("adjudication does not match annotation packet")
    if adjudication.annotation_policy_version != packet.annotation_policy_version:
        raise ValueError("adjudication annotation policy does not match packet")
    submission_ids = tuple(sorted(item.submission_id for item in submissions))
    if adjudication.source_submission_ids != submission_ids:
        raise ValueError("adjudication must account for every reviewer submission supplied for the packet")
    reviewer_ids = {item.reviewer_id for item in submissions}
    if adjudication.adjudicator_id in reviewer_ids:
        raise ValueError("adjudicator must be independent from source reviewers")
    if any(item.submitted_at > adjudication.adjudicated_at for item in submissions):
        raise ValueError("adjudication cannot precede reviewer submissions")


def _validate_truth(direction: StanceDirection, disposition: EvidenceDisposition, prefix: str) -> None:
    if direction is StanceDirection.CONTRADICTORY and disposition is not EvidenceDisposition.CONTRADICTORY:
        raise ValueError(f"{prefix} contradictory direction requires contradictory disposition")
    if disposition is EvidenceDisposition.CONTRADICTORY and direction is not StanceDirection.CONTRADICTORY:
        raise ValueError(f"{prefix} contradictory disposition requires contradictory direction")
    if disposition is EvidenceDisposition.ABSTAINED and direction is not StanceDirection.NEUTRAL:
        raise ValueError(f"{prefix} abstained disposition requires neutral direction")


def _validate_dimensions(dimensions: tuple[DimensionSemanticLabel, ...], prefix: str) -> None:
    if tuple(sorted(dimensions, key=lambda item: item.dimension.value)) != dimensions:
        raise ValueError(f"{prefix} dimensions must be sorted")
    if len({item.dimension for item in dimensions}) != len(dimensions):
        raise ValueError(f"{prefix} dimensions cannot repeat")


def _packet_id_values(
    *,
    annotation_policy_version: str,
    family_id: str,
    source_id: str,
    institution: str,
    document_type: str,
    currency: str,
    previous_version_id: str,
    current_version_id: str,
    previous_document_url: str,
    current_document_url: str,
    previous_published_at: datetime,
    current_published_at: datetime,
    previous_available_at: datetime,
    current_available_at: datetime,
    previous_text_sha256: str,
    current_text_sha256: str,
    previous_text: str,
    current_text: str,
    diff_id: str,
    added: tuple[DocumentTextChange, ...],
    removed: tuple[DocumentTextChange, ...],
) -> str:
    payload = {
        "schema_version": ANNOTATION_PACKET_SCHEMA_VERSION,
        "research_only": True,
        "execution_authority": False,
        "annotation_policy_version": annotation_policy_version,
        "family_id": family_id,
        "source_id": source_id,
        "institution": institution,
        "document_type": document_type,
        "currency": currency,
        "previous_version_id": previous_version_id,
        "current_version_id": current_version_id,
        "previous_document_url": previous_document_url,
        "current_document_url": current_document_url,
        "previous_published_at": previous_published_at.isoformat(),
        "current_published_at": current_published_at.isoformat(),
        "previous_available_at": previous_available_at.isoformat(),
        "current_available_at": current_available_at.isoformat(),
        "previous_text_sha256": previous_text_sha256,
        "current_text_sha256": current_text_sha256,
        "previous_text": previous_text,
        "current_text": current_text,
        "diff_id": diff_id,
        "added": [_change_to_dict(value) for value in added],
        "removed": [_change_to_dict(value) for value in removed],
    }
    return hashlib.sha256(_canonical_json(payload)).hexdigest()


def _batch_id(
    *,
    family_id: str,
    annotation_policy_version: str,
    as_of: datetime,
    packet_ids: tuple[str, ...],
) -> str:
    payload = {
        "schema_version": ANNOTATION_BATCH_SCHEMA_VERSION,
        "research_only": True,
        "execution_authority": False,
        "family_id": family_id,
        "annotation_policy_version": annotation_policy_version,
        "as_of": as_of.isoformat(),
        "packet_ids": list(packet_ids),
    }
    return hashlib.sha256(_canonical_json(payload)).hexdigest()


def _submission_id_values(
    *,
    packet_id: str,
    annotation_policy_version: str,
    reviewer_id: str,
    submitted_at: datetime,
    direction: StanceDirection,
    disposition: EvidenceDisposition,
    dimensions: tuple[DimensionSemanticLabel, ...],
) -> str:
    payload = {
        "schema_version": REVIEWER_SUBMISSION_SCHEMA_VERSION,
        "research_only": True,
        "execution_authority": False,
        "packet_id": packet_id,
        "annotation_policy_version": annotation_policy_version,
        "reviewer_id": reviewer_id,
        "submitted_at": submitted_at.isoformat(),
        "direction": direction.value,
        "disposition": disposition.value,
        "dimensions": [_dimension_to_dict(value) for value in dimensions],
    }
    return hashlib.sha256(_canonical_json(payload)).hexdigest()


def _adjudication_id_values(
    *,
    packet_id: str,
    annotation_policy_version: str,
    source_submission_ids: tuple[str, ...],
    adjudicator_id: str,
    adjudicated_at: datetime,
    direction: StanceDirection,
    disposition: EvidenceDisposition,
    dimensions: tuple[DimensionSemanticLabel, ...],
) -> str:
    payload = {
        "schema_version": ADJUDICATION_SCHEMA_VERSION,
        "research_only": True,
        "execution_authority": False,
        "packet_id": packet_id,
        "annotation_policy_version": annotation_policy_version,
        "source_submission_ids": list(source_submission_ids),
        "adjudicator_id": adjudicator_id,
        "adjudicated_at": adjudicated_at.isoformat(),
        "direction": direction.value,
        "disposition": disposition.value,
        "dimensions": [_dimension_to_dict(value) for value in dimensions],
    }
    return hashlib.sha256(_canonical_json(payload)).hexdigest()


def _audit_id_values(
    *,
    batch_id: str,
    packet_id: str,
    adjudication_id: str,
    semantic_label_id: str,
    source_submission_ids: tuple[str, ...],
    reviewer_ids: tuple[str, ...],
    reviewer_overall_agreement: bool,
    reviewer_dimension_agreement: bool,
) -> str:
    payload = {
        "schema_version": FINALIZATION_AUDIT_SCHEMA_VERSION,
        "research_only": True,
        "execution_authority": False,
        "batch_id": batch_id,
        "packet_id": packet_id,
        "adjudication_id": adjudication_id,
        "semantic_label_id": semantic_label_id,
        "source_submission_ids": list(source_submission_ids),
        "reviewer_ids": list(reviewer_ids),
        "reviewer_overall_agreement": reviewer_overall_agreement,
        "reviewer_dimension_agreement": reviewer_dimension_agreement,
    }
    return hashlib.sha256(_canonical_json(payload)).hexdigest()


def _change_to_dict(item: DocumentTextChange) -> dict[str, object]:
    return {
        "side": item.side,
        "paragraph_index": item.paragraph_index,
        "text": item.text,
        "text_sha256": item.text_sha256,
    }


def _dimension_to_dict(item: DimensionSemanticLabel) -> dict[str, object]:
    return {
        "dimension": item.dimension.value,
        "direction": item.direction.value,
        "disposition": item.disposition.value,
    }


def _changes_from_value(value: object, name: str) -> tuple[DocumentTextChange, ...]:
    records = _require_list(value, name)
    result: list[DocumentTextChange] = []
    for record in records:
        raw = _require_mapping(record, f"{name} change")
        _require_exact_keys(raw, _CHANGE_KEYS, f"{name} change")
        result.append(
            DocumentTextChange(
                side=_require_str(raw.get("side"), "side"),
                paragraph_index=_require_int(raw.get("paragraph_index"), "paragraph_index"),
                text=_require_str(raw.get("text"), "text"),
                text_sha256=_require_str(raw.get("text_sha256"), "text_sha256"),
            )
        )
    return tuple(result)


def _dimensions_from_value(value: object) -> tuple[DimensionSemanticLabel, ...]:
    records = _require_list(value, "dimensions")
    result: list[DimensionSemanticLabel] = []
    for record in records:
        raw = _require_mapping(record, "dimension")
        _require_exact_keys(raw, _DIMENSION_KEYS, "dimension")
        result.append(
            DimensionSemanticLabel(
                dimension=PolicyDimension(_require_str(raw.get("dimension"), "dimension")),
                direction=StanceDirection(_require_str(raw.get("direction"), "direction")),
                disposition=EvidenceDisposition(_require_str(raw.get("disposition"), "disposition")),
            )
        )
    return tuple(sorted(result, key=lambda item: item.dimension.value))


def _load_json_object(path: str | Path, name: str) -> Mapping[str, object]:
    try:
        value = json.loads(Path(path).read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError(f"{name} file is not valid JSON") from exc
    return _require_mapping(value, name)


def _load_jsonl_objects(path: str | Path, name: str) -> tuple[Mapping[str, object], ...]:
    result: list[Mapping[str, object]] = []
    for line_number, line in enumerate(Path(path).read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        try:
            value = json.loads(line)
        except json.JSONDecodeError as exc:
            raise ValueError(f"{name} JSONL line {line_number} is not valid JSON") from exc
        result.append(_require_mapping(value, f"{name} JSONL line {line_number}"))
    if not result:
        raise ValueError(f"{name} file is empty")
    return tuple(result)


def _require_mapping(value: object, name: str) -> Mapping[str, object]:
    if not isinstance(value, dict):
        raise ValueError(f"{name} must be an object")
    return value


def _require_list(value: object, name: str) -> list[object]:
    if not isinstance(value, list):
        raise ValueError(f"{name} must be a list")
    return value


def _require_str(value: object, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} must be a non-empty string")
    return value


def _require_bool(value: object, name: str) -> bool:
    if not isinstance(value, bool):
        raise ValueError(f"{name} must be a JSON boolean")
    return value


def _require_int(value: object, name: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool):
        raise ValueError(f"{name} must be an integer")
    return value


def _require_datetime(value: object, name: str) -> datetime:
    text = _require_str(value, name)
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError as exc:
        raise ValueError(f"{name} must be ISO-8601") from exc
    if parsed.tzinfo is None:
        raise ValueError(f"{name} must be timezone-aware")
    return parsed


def _require_str_tuple(value: object, name: str) -> tuple[str, ...]:
    return tuple(_require_str(item, name) for item in _require_list(value, name))


def _require_exact_keys(value: Mapping[str, object], expected: frozenset[str], name: str) -> None:
    actual = frozenset(value.keys())
    if actual != expected:
        missing = sorted(expected - actual)
        unexpected = sorted(actual - expected)
        raise ValueError(f"{name} keys do not match schema; missing={missing} unexpected={unexpected}")


def _canonical_json(value: object) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def _require_sha256(value: str, name: str) -> None:
    if len(value) != 64:
        raise ValueError(f"{name} must be a SHA-256 hex digest")
    try:
        int(value, 16)
    except ValueError as exc:
        raise ValueError(f"{name} must be a SHA-256 hex digest") from exc
