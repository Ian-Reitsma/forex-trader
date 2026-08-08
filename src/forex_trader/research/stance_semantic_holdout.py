from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Iterable, Mapping

from forex_trader.intelligence.official_documents import OfficialDocumentVersion, compare_document_versions
from forex_trader.research.stance_annotation_workflow import (
    ANNOTATION_BATCH_SCHEMA_VERSION,
    AdjudicationRecord,
    AnnotationBatch,
    AnnotationBatchManifest,
    ReviewerSubmission,
    annotation_batch_to_dict,
    build_blinded_annotation_batch,
)
from forex_trader.research.stance_semantic_validation import (
    CentralBankSemanticLabel,
    official_document_diff_id,
)


SEMANTIC_HOLDOUT_SCHEMA_VERSION = "central-bank-semantic-holdout-v1"
SEMANTIC_PARTITION_AUDIT_SCHEMA_VERSION = "central-bank-semantic-partition-audit-v1"
SEMANTIC_HOLDOUT_SPLIT_NUMERATOR = 2
SEMANTIC_HOLDOUT_SPLIT_DENOMINATOR = 3
SEMANTIC_HOLDOUT_MIN_PACKETS = 3

_MANIFEST_KEYS = frozenset(
    {
        "manifest_id",
        "schema_version",
        "research_only",
        "execution_authority",
        "source_batch_id",
        "family_id",
        "annotation_policy_version",
        "as_of",
        "source_packet_count",
        "split_numerator",
        "split_denominator",
        "calibration_packet_count",
        "holdout_packet_count",
        "calibration_packet_ids",
        "holdout_packet_ids",
    }
)


class SemanticPartition(str, Enum):
    CALIBRATION = "calibration"
    HOLDOUT = "holdout"


@dataclass(frozen=True, slots=True)
class SemanticHoldoutManifest:
    manifest_id: str
    schema_version: str
    research_only: bool
    execution_authority: bool
    source_batch_id: str
    family_id: str
    annotation_policy_version: str
    as_of: datetime
    source_packet_count: int
    split_numerator: int
    split_denominator: int
    calibration_packet_count: int
    holdout_packet_count: int
    calibration_packet_ids: tuple[str, ...]
    holdout_packet_ids: tuple[str, ...]

    def __post_init__(self) -> None:
        if self.schema_version != SEMANTIC_HOLDOUT_SCHEMA_VERSION:
            raise ValueError("unsupported semantic holdout manifest schema")
        if self.research_only is not True or self.execution_authority is not False:
            raise ValueError("semantic holdout manifests must remain research-only")
        _require_sha256(self.source_batch_id, "source_batch_id")
        _require_sha256(self.manifest_id, "manifest_id")
        if not self.family_id.strip() or not self.annotation_policy_version.strip():
            raise ValueError("semantic holdout family and annotation policy are required")
        if self.as_of.tzinfo is None:
            raise ValueError("semantic holdout as_of must be timezone-aware")
        if (
            self.split_numerator != SEMANTIC_HOLDOUT_SPLIT_NUMERATOR
            or self.split_denominator != SEMANTIC_HOLDOUT_SPLIT_DENOMINATOR
        ):
            raise ValueError("semantic holdout split policy must remain fixed at two-thirds / one-third")
        if self.source_packet_count < SEMANTIC_HOLDOUT_MIN_PACKETS:
            raise ValueError("semantic holdout requires at least three source packets")
        if self.calibration_packet_count != len(self.calibration_packet_ids):
            raise ValueError("semantic holdout calibration denominator is inconsistent")
        if self.holdout_packet_count != len(self.holdout_packet_ids):
            raise ValueError("semantic holdout holdout denominator is inconsistent")
        if self.calibration_packet_count + self.holdout_packet_count != self.source_packet_count:
            raise ValueError("semantic holdout partition denominators do not cover the source batch")
        expected_split_index = (SEMANTIC_HOLDOUT_SPLIT_NUMERATOR * self.source_packet_count) // SEMANTIC_HOLDOUT_SPLIT_DENOMINATOR
        if self.calibration_packet_count != expected_split_index:
            raise ValueError("semantic holdout calibration count does not match the frozen chronological split")
        if self.calibration_packet_count < 1 or self.holdout_packet_count < 1:
            raise ValueError("semantic holdout requires non-empty calibration and holdout partitions")
        combined = self.calibration_packet_ids + self.holdout_packet_ids
        if len(set(combined)) != len(combined):
            raise ValueError("semantic holdout packet IDs must be unique across partitions")
        for packet_id in combined:
            _require_sha256(packet_id, "semantic holdout packet_id")
        expected_id = _holdout_manifest_id(
            source_batch_id=self.source_batch_id,
            family_id=self.family_id,
            annotation_policy_version=self.annotation_policy_version,
            as_of=self.as_of,
            source_packet_count=self.source_packet_count,
            calibration_packet_ids=self.calibration_packet_ids,
            holdout_packet_ids=self.holdout_packet_ids,
        )
        if self.manifest_id != expected_id:
            raise ValueError("semantic holdout manifest ID does not match its immutable payload")

    def packet_ids_for(self, partition: SemanticPartition) -> tuple[str, ...]:
        if partition is SemanticPartition.CALIBRATION:
            return self.calibration_packet_ids
        return self.holdout_packet_ids


@dataclass(frozen=True, slots=True)
class PartitionFinalizationAudit:
    audit_id: str
    schema_version: str
    research_only: bool
    execution_authority: bool
    holdout_manifest_id: str
    source_batch_id: str
    partition_batch_id: str
    partition: SemanticPartition
    packet_id: str
    adjudication_id: str
    semantic_label_id: str
    source_submission_ids: tuple[str, ...]
    reviewer_ids: tuple[str, ...]
    reviewer_overall_agreement: bool
    reviewer_dimension_agreement: bool

    def __post_init__(self) -> None:
        if self.schema_version != SEMANTIC_PARTITION_AUDIT_SCHEMA_VERSION:
            raise ValueError("unsupported semantic partition audit schema")
        if self.research_only is not True or self.execution_authority is not False:
            raise ValueError("semantic partition audits must remain research-only")
        for value, name in (
            (self.holdout_manifest_id, "holdout_manifest_id"),
            (self.source_batch_id, "source_batch_id"),
            (self.partition_batch_id, "partition_batch_id"),
            (self.packet_id, "packet_id"),
            (self.adjudication_id, "adjudication_id"),
            (self.semantic_label_id, "semantic_label_id"),
        ):
            _require_sha256(value, name)
        if len(self.source_submission_ids) < 2:
            raise ValueError("semantic partition audit requires at least two source submissions")
        if tuple(sorted(set(self.source_submission_ids))) != self.source_submission_ids:
            raise ValueError("semantic partition audit submission IDs must be sorted and unique")
        if tuple(sorted(set(self.reviewer_ids))) != self.reviewer_ids:
            raise ValueError("semantic partition audit reviewer IDs must be sorted and unique")
        if len(self.source_submission_ids) != len(self.reviewer_ids):
            raise ValueError("semantic partition audit reviewer/submission denominators must match")
        expected_id = _partition_audit_id(
            holdout_manifest_id=self.holdout_manifest_id,
            source_batch_id=self.source_batch_id,
            partition_batch_id=self.partition_batch_id,
            partition=self.partition,
            packet_id=self.packet_id,
            adjudication_id=self.adjudication_id,
            semantic_label_id=self.semantic_label_id,
            source_submission_ids=self.source_submission_ids,
            reviewer_ids=self.reviewer_ids,
            reviewer_overall_agreement=self.reviewer_overall_agreement,
            reviewer_dimension_agreement=self.reviewer_dimension_agreement,
        )
        if self.audit_id != expected_id:
            raise ValueError("semantic partition audit ID does not match its immutable payload")


@dataclass(frozen=True, slots=True)
class FinalizedPartitionAnnotation:
    semantic_label: CentralBankSemanticLabel
    audit: PartitionFinalizationAudit

    def __post_init__(self) -> None:
        if self.semantic_label.label_id != self.audit.semantic_label_id:
            raise ValueError("finalized partition label does not match its audit")


def build_semantic_holdout_manifest(batch: AnnotationBatch) -> SemanticHoldoutManifest:
    packet_count = batch.manifest.packet_count
    if packet_count < SEMANTIC_HOLDOUT_MIN_PACKETS:
        raise ValueError("semantic holdout requires at least three frozen annotation packets")
    _validate_source_batch_order(batch)
    split_index = (SEMANTIC_HOLDOUT_SPLIT_NUMERATOR * packet_count) // SEMANTIC_HOLDOUT_SPLIT_DENOMINATOR
    if split_index < 1 or split_index >= packet_count:
        raise ValueError("semantic holdout split produced an empty partition")
    packet_ids = batch.manifest.packet_ids
    calibration_ids = packet_ids[:split_index]
    holdout_ids = packet_ids[split_index:]
    manifest_id = _holdout_manifest_id(
        source_batch_id=batch.manifest.batch_id,
        family_id=batch.manifest.family_id,
        annotation_policy_version=batch.manifest.annotation_policy_version,
        as_of=batch.manifest.as_of,
        source_packet_count=packet_count,
        calibration_packet_ids=calibration_ids,
        holdout_packet_ids=holdout_ids,
    )
    return SemanticHoldoutManifest(
        manifest_id=manifest_id,
        schema_version=SEMANTIC_HOLDOUT_SCHEMA_VERSION,
        research_only=True,
        execution_authority=False,
        source_batch_id=batch.manifest.batch_id,
        family_id=batch.manifest.family_id,
        annotation_policy_version=batch.manifest.annotation_policy_version,
        as_of=batch.manifest.as_of,
        source_packet_count=packet_count,
        split_numerator=SEMANTIC_HOLDOUT_SPLIT_NUMERATOR,
        split_denominator=SEMANTIC_HOLDOUT_SPLIT_DENOMINATOR,
        calibration_packet_count=len(calibration_ids),
        holdout_packet_count=len(holdout_ids),
        calibration_packet_ids=calibration_ids,
        holdout_packet_ids=holdout_ids,
    )


def validate_semantic_holdout_manifest(batch: AnnotationBatch, manifest: SemanticHoldoutManifest) -> None:
    rebuilt = build_semantic_holdout_manifest(batch)
    if rebuilt != manifest:
        raise ValueError("semantic holdout manifest does not match the complete frozen annotation batch")


def build_partition_annotation_batch(
    batch: AnnotationBatch,
    manifest: SemanticHoldoutManifest,
    partition: SemanticPartition,
) -> AnnotationBatch:
    validate_semantic_holdout_manifest(batch, manifest)
    selected_ids = manifest.packet_ids_for(partition)
    packet_by_id = {item.packet_id: item for item in batch.packets}
    packets = tuple(packet_by_id[packet_id] for packet_id in selected_ids)
    partition_batch_id = _annotation_batch_id(
        family_id=batch.manifest.family_id,
        annotation_policy_version=batch.manifest.annotation_policy_version,
        as_of=batch.manifest.as_of,
        packet_ids=selected_ids,
    )
    partition_manifest = AnnotationBatchManifest(
        batch_id=partition_batch_id,
        schema_version=ANNOTATION_BATCH_SCHEMA_VERSION,
        research_only=True,
        execution_authority=False,
        family_id=batch.manifest.family_id,
        annotation_policy_version=batch.manifest.annotation_policy_version,
        as_of=batch.manifest.as_of,
        packet_count=len(selected_ids),
        packet_ids=selected_ids,
    )
    return AnnotationBatch(manifest=partition_manifest, packets=packets)


def finalize_semantic_partition(
    source_batch: AnnotationBatch,
    holdout_manifest: SemanticHoldoutManifest,
    partition_batch: AnnotationBatch,
    partition: SemanticPartition,
    submissions: Iterable[ReviewerSubmission],
    adjudications: Iterable[AdjudicationRecord],
    versions: Iterable[OfficialDocumentVersion],
) -> tuple[FinalizedPartitionAnnotation, ...]:
    version_records = tuple(versions)
    rebuilt_source = build_blinded_annotation_batch(
        version_records,
        annotation_policy_version=source_batch.manifest.annotation_policy_version,
        as_of=source_batch.manifest.as_of,
    )
    if rebuilt_source != source_batch:
        raise ValueError("source annotation batch does not match reconstructed frozen official-document evidence")
    validate_semantic_holdout_manifest(source_batch, holdout_manifest)
    expected_partition_batch = build_partition_annotation_batch(source_batch, holdout_manifest, partition)
    if expected_partition_batch != partition_batch:
        raise ValueError("partition annotation batch does not match the sealed holdout manifest")

    selected_ids = holdout_manifest.packet_ids_for(partition)
    selected_set = set(selected_ids)
    submission_records = tuple(submissions)
    adjudication_records = tuple(adjudications)
    if len({item.submission_id for item in submission_records}) != len(submission_records):
        raise ValueError("semantic partition finalization cannot contain duplicate reviewer submission IDs")
    if len({item.adjudication_id for item in adjudication_records}) != len(adjudication_records):
        raise ValueError("semantic partition finalization cannot contain duplicate adjudication IDs")
    if any(item.packet_id not in selected_set for item in submission_records):
        raise ValueError("reviewer submission crosses the sealed semantic partition boundary")
    if any(item.packet_id not in selected_set for item in adjudication_records):
        raise ValueError("adjudication crosses the sealed semantic partition boundary")

    submissions_by_packet: dict[str, list[ReviewerSubmission]] = {}
    for submission in submission_records:
        submissions_by_packet.setdefault(submission.packet_id, []).append(submission)
    adjudications_by_packet: dict[str, list[AdjudicationRecord]] = {}
    for adjudication in adjudication_records:
        adjudications_by_packet.setdefault(adjudication.packet_id, []).append(adjudication)

    packet_by_id = {item.packet_id: item for item in partition_batch.packets}
    version_by_id = {item.version_id: item for item in version_records}
    finalized: list[FinalizedPartitionAnnotation] = []
    for packet_id in selected_ids:
        packet = packet_by_id[packet_id]
        source_submissions = tuple(submissions_by_packet.get(packet_id, ()))
        _validate_partition_submissions(packet_id, packet.annotation_policy_version, source_submissions)
        packet_adjudications = tuple(adjudications_by_packet.get(packet_id, ()))
        if len(packet_adjudications) != 1:
            raise ValueError("every packet in the selected semantic partition requires exactly one adjudication")
        adjudication = packet_adjudications[0]
        _validate_partition_adjudication(packet_id, packet.annotation_policy_version, source_submissions, adjudication)
        previous = version_by_id.get(packet.previous_version_id)
        current = version_by_id.get(packet.current_version_id)
        if previous is None or current is None:
            raise ValueError("semantic partition source versions are missing during finalization")
        diff = compare_document_versions(previous, current)
        if official_document_diff_id(diff) != packet.diff_id:
            raise ValueError("semantic partition packet diff changed before label finalization")
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
        audit_id = _partition_audit_id(
            holdout_manifest_id=holdout_manifest.manifest_id,
            source_batch_id=source_batch.manifest.batch_id,
            partition_batch_id=partition_batch.manifest.batch_id,
            partition=partition,
            packet_id=packet_id,
            adjudication_id=adjudication.adjudication_id,
            semantic_label_id=semantic_label.label_id,
            source_submission_ids=submission_ids,
            reviewer_ids=reviewer_ids,
            reviewer_overall_agreement=overall_agreement,
            reviewer_dimension_agreement=dimension_agreement,
        )
        audit = PartitionFinalizationAudit(
            audit_id=audit_id,
            schema_version=SEMANTIC_PARTITION_AUDIT_SCHEMA_VERSION,
            research_only=True,
            execution_authority=False,
            holdout_manifest_id=holdout_manifest.manifest_id,
            source_batch_id=source_batch.manifest.batch_id,
            partition_batch_id=partition_batch.manifest.batch_id,
            partition=partition,
            packet_id=packet_id,
            adjudication_id=adjudication.adjudication_id,
            semantic_label_id=semantic_label.label_id,
            source_submission_ids=submission_ids,
            reviewer_ids=reviewer_ids,
            reviewer_overall_agreement=overall_agreement,
            reviewer_dimension_agreement=dimension_agreement,
        )
        finalized.append(FinalizedPartitionAnnotation(semantic_label=semantic_label, audit=audit))
    if len(finalized) != len(selected_ids):
        raise ValueError("semantic partition finalization did not account for every sealed partition packet")
    return tuple(finalized)


def semantic_holdout_manifest_to_dict(manifest: SemanticHoldoutManifest) -> dict[str, object]:
    return {
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


def partition_batch_to_dict(batch: AnnotationBatch) -> dict[str, object]:
    return annotation_batch_to_dict(batch)


def partition_finalization_audit_to_dict(audit: PartitionFinalizationAudit) -> dict[str, object]:
    return {
        "audit_id": audit.audit_id,
        "schema_version": audit.schema_version,
        "research_only": audit.research_only,
        "execution_authority": audit.execution_authority,
        "holdout_manifest_id": audit.holdout_manifest_id,
        "source_batch_id": audit.source_batch_id,
        "partition_batch_id": audit.partition_batch_id,
        "partition": audit.partition.value,
        "packet_id": audit.packet_id,
        "adjudication_id": audit.adjudication_id,
        "semantic_label_id": audit.semantic_label_id,
        "source_submission_ids": list(audit.source_submission_ids),
        "reviewer_ids": list(audit.reviewer_ids),
        "reviewer_overall_agreement": audit.reviewer_overall_agreement,
        "reviewer_dimension_agreement": audit.reviewer_dimension_agreement,
    }


def load_semantic_holdout_manifest(path: str | Path) -> SemanticHoldoutManifest:
    try:
        parsed = json.loads(Path(path).read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError("semantic holdout manifest file is not valid JSON") from exc
    raw = _require_mapping(parsed, "semantic holdout manifest")
    actual_keys = frozenset(raw.keys())
    if actual_keys != _MANIFEST_KEYS:
        missing = sorted(_MANIFEST_KEYS - actual_keys)
        unexpected = sorted(actual_keys - _MANIFEST_KEYS)
        raise ValueError(f"semantic holdout manifest keys do not match schema; missing={missing} unexpected={unexpected}")
    return SemanticHoldoutManifest(
        manifest_id=_require_str(raw.get("manifest_id"), "manifest_id"),
        schema_version=_require_str(raw.get("schema_version"), "schema_version"),
        research_only=_require_bool(raw.get("research_only"), "research_only"),
        execution_authority=_require_bool(raw.get("execution_authority"), "execution_authority"),
        source_batch_id=_require_str(raw.get("source_batch_id"), "source_batch_id"),
        family_id=_require_str(raw.get("family_id"), "family_id"),
        annotation_policy_version=_require_str(raw.get("annotation_policy_version"), "annotation_policy_version"),
        as_of=_require_datetime(raw.get("as_of"), "as_of"),
        source_packet_count=_require_int(raw.get("source_packet_count"), "source_packet_count"),
        split_numerator=_require_int(raw.get("split_numerator"), "split_numerator"),
        split_denominator=_require_int(raw.get("split_denominator"), "split_denominator"),
        calibration_packet_count=_require_int(raw.get("calibration_packet_count"), "calibration_packet_count"),
        holdout_packet_count=_require_int(raw.get("holdout_packet_count"), "holdout_packet_count"),
        calibration_packet_ids=_require_str_tuple(raw.get("calibration_packet_ids"), "calibration_packet_ids"),
        holdout_packet_ids=_require_str_tuple(raw.get("holdout_packet_ids"), "holdout_packet_ids"),
    )


def _validate_source_batch_order(batch: AnnotationBatch) -> None:
    ordered = tuple(sorted(batch.packets, key=lambda item: (item.current_available_at, item.current_version_id)))
    if ordered != batch.packets:
        raise ValueError("semantic holdout source batch must preserve deterministic chronological packet order")
    if tuple(item.packet_id for item in batch.packets) != batch.manifest.packet_ids:
        raise ValueError("semantic holdout source batch manifest does not match packet order")


def _validate_partition_submissions(
    packet_id: str,
    annotation_policy_version: str,
    submissions: tuple[ReviewerSubmission, ...],
) -> None:
    if len(submissions) < 2:
        raise ValueError("every semantic partition packet requires at least two independent reviewer submissions")
    if any(item.packet_id != packet_id for item in submissions):
        raise ValueError("semantic partition reviewer submissions must reference one packet")
    if any(item.annotation_policy_version != annotation_policy_version for item in submissions):
        raise ValueError("semantic partition reviewer submission policy does not match packet policy")
    reviewer_ids = tuple(item.reviewer_id for item in submissions)
    if len(set(reviewer_ids)) != len(reviewer_ids):
        raise ValueError("semantic partition reviewers must be independent pseudonymous reviewers")


def _validate_partition_adjudication(
    packet_id: str,
    annotation_policy_version: str,
    submissions: tuple[ReviewerSubmission, ...],
    adjudication: AdjudicationRecord,
) -> None:
    if adjudication.packet_id != packet_id:
        raise ValueError("semantic partition adjudication packet does not match source submissions")
    if adjudication.annotation_policy_version != annotation_policy_version:
        raise ValueError("semantic partition adjudication policy does not match packet policy")
    submission_ids = tuple(sorted(item.submission_id for item in submissions))
    if adjudication.source_submission_ids != submission_ids:
        raise ValueError("semantic partition adjudication must account for every reviewer submission for its packet")
    reviewer_ids = {item.reviewer_id for item in submissions}
    if adjudication.adjudicator_id in reviewer_ids:
        raise ValueError("semantic partition adjudicator must be independent from source reviewers")
    if any(item.submitted_at > adjudication.adjudicated_at for item in submissions):
        raise ValueError("semantic partition adjudication cannot precede a reviewer submission")


def _holdout_manifest_id(
    *,
    source_batch_id: str,
    family_id: str,
    annotation_policy_version: str,
    as_of: datetime,
    source_packet_count: int,
    calibration_packet_ids: tuple[str, ...],
    holdout_packet_ids: tuple[str, ...],
) -> str:
    payload = {
        "schema_version": SEMANTIC_HOLDOUT_SCHEMA_VERSION,
        "research_only": True,
        "execution_authority": False,
        "source_batch_id": source_batch_id,
        "family_id": family_id,
        "annotation_policy_version": annotation_policy_version,
        "as_of": as_of.isoformat(),
        "source_packet_count": source_packet_count,
        "split_numerator": SEMANTIC_HOLDOUT_SPLIT_NUMERATOR,
        "split_denominator": SEMANTIC_HOLDOUT_SPLIT_DENOMINATOR,
        "calibration_packet_ids": list(calibration_packet_ids),
        "holdout_packet_ids": list(holdout_packet_ids),
    }
    return hashlib.sha256(_canonical_json(payload)).hexdigest()


def _annotation_batch_id(
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


def _partition_audit_id(
    *,
    holdout_manifest_id: str,
    source_batch_id: str,
    partition_batch_id: str,
    partition: SemanticPartition,
    packet_id: str,
    adjudication_id: str,
    semantic_label_id: str,
    source_submission_ids: tuple[str, ...],
    reviewer_ids: tuple[str, ...],
    reviewer_overall_agreement: bool,
    reviewer_dimension_agreement: bool,
) -> str:
    payload = {
        "schema_version": SEMANTIC_PARTITION_AUDIT_SCHEMA_VERSION,
        "research_only": True,
        "execution_authority": False,
        "holdout_manifest_id": holdout_manifest_id,
        "source_batch_id": source_batch_id,
        "partition_batch_id": partition_batch_id,
        "partition": partition.value,
        "packet_id": packet_id,
        "adjudication_id": adjudication_id,
        "semantic_label_id": semantic_label_id,
        "source_submission_ids": list(source_submission_ids),
        "reviewer_ids": list(reviewer_ids),
        "reviewer_overall_agreement": reviewer_overall_agreement,
        "reviewer_dimension_agreement": reviewer_dimension_agreement,
    }
    return hashlib.sha256(_canonical_json(payload)).hexdigest()


def _canonical_json(value: object) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def _require_mapping(value: object, name: str) -> Mapping[str, object]:
    if not isinstance(value, dict):
        raise ValueError(f"{name} must be an object")
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
    if not isinstance(value, list):
        raise ValueError(f"{name} must be a list")
    return tuple(_require_str(item, name) for item in value)


def _require_sha256(value: str, name: str) -> None:
    if len(value) != 64:
        raise ValueError(f"{name} must be a SHA-256 hex digest")
    try:
        int(value, 16)
    except ValueError as exc:
        raise ValueError(f"{name} must be a SHA-256 hex digest") from exc
