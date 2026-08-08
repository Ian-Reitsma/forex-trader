from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from typing import Iterable, Mapping

from forex_trader import __version__
from forex_trader.intelligence.official_documents import (
    OfficialDocumentDiff,
    OfficialDocumentVersion,
    compare_document_versions,
)
from forex_trader.research.central_bank_stance import (
    STANCE_RULESET_VERSION,
    EvidenceDisposition,
    PolicyDimension,
    StanceDirection,
    extract_central_bank_stance,
)


SEMANTIC_LABEL_SCHEMA_VERSION = "central-bank-semantic-label-v1"
SEMANTIC_EVALUATION_SCHEMA_VERSION = "central-bank-semantic-evaluation-v1"
HUMAN_REVIEW_SOURCE = "human_review"
_DIRECTIONAL = {StanceDirection.HAWKISH, StanceDirection.DOVISH}


@dataclass(frozen=True, slots=True)
class DimensionSemanticLabel:
    dimension: PolicyDimension
    direction: StanceDirection
    disposition: EvidenceDisposition

    def __post_init__(self) -> None:
        _validate_direction_disposition(self.direction, self.disposition, "dimension semantic label")


@dataclass(frozen=True, slots=True)
class CentralBankSemanticLabel:
    label_id: str
    schema_version: str
    research_only: bool
    execution_authority: bool
    source: str
    diff_id: str
    family_id: str
    previous_version_id: str
    current_version_id: str
    annotation_policy_version: str
    annotator_ids: tuple[str, ...]
    adjudicated: bool
    adjudicator_id: str | None
    labeled_at: datetime
    direction: StanceDirection
    disposition: EvidenceDisposition
    dimensions: tuple[DimensionSemanticLabel, ...]

    def __post_init__(self) -> None:
        if self.schema_version != SEMANTIC_LABEL_SCHEMA_VERSION:
            raise ValueError("unsupported central-bank semantic label schema")
        if self.research_only is not True or self.execution_authority is not False:
            raise ValueError("semantic labels must remain research-only with no execution authority")
        if self.source != HUMAN_REVIEW_SOURCE:
            raise ValueError("semantic ground-truth labels must be explicitly human-reviewed")
        _require_sha256(self.diff_id, "semantic label diff_id")
        if not self.family_id.strip() or not self.previous_version_id.strip() or not self.current_version_id.strip():
            raise ValueError("semantic label document lineage identity is required")
        if self.previous_version_id == self.current_version_id:
            raise ValueError("semantic label current and previous versions must differ")
        if not self.annotation_policy_version.strip():
            raise ValueError("semantic label annotation policy version is required")
        if not self.annotator_ids or any(not item.strip() or item != item.strip() for item in self.annotator_ids):
            raise ValueError("semantic label requires normalized non-empty annotator IDs")
        if tuple(sorted(set(self.annotator_ids))) != self.annotator_ids:
            raise ValueError("semantic label annotator IDs must be sorted and unique")
        if self.adjudicated:
            if len(self.annotator_ids) < 2:
                raise ValueError("adjudicated semantic label requires at least two source annotators")
            if self.adjudicator_id is None or not self.adjudicator_id.strip():
                raise ValueError("adjudicated semantic label requires an adjudicator ID")
        elif self.adjudicator_id is not None:
            raise ValueError("unadjudicated semantic label cannot name an adjudicator")
        if self.labeled_at.tzinfo is None:
            raise ValueError("semantic label labeled_at must be timezone-aware")
        _validate_direction_disposition(self.direction, self.disposition, "semantic label")
        if tuple(sorted(self.dimensions, key=lambda item: item.dimension.value)) != self.dimensions:
            raise ValueError("semantic label dimensions must be sorted by dimension")
        if len({item.dimension for item in self.dimensions}) != len(self.dimensions):
            raise ValueError("semantic label dimensions cannot repeat")
        expected_id = _semantic_label_id(
            diff_id=self.diff_id,
            family_id=self.family_id,
            previous_version_id=self.previous_version_id,
            current_version_id=self.current_version_id,
            annotation_policy_version=self.annotation_policy_version,
            annotator_ids=self.annotator_ids,
            adjudicated=self.adjudicated,
            adjudicator_id=self.adjudicator_id,
            labeled_at=self.labeled_at,
            direction=self.direction,
            disposition=self.disposition,
            dimensions=self.dimensions,
        )
        if self.label_id != expected_id:
            raise ValueError("semantic label ID does not match its immutable annotation payload")

    @classmethod
    def create(
        cls,
        diff: OfficialDocumentDiff,
        *,
        annotation_policy_version: str,
        annotator_ids: Iterable[str],
        adjudicated: bool,
        adjudicator_id: str | None,
        labeled_at: datetime,
        direction: StanceDirection,
        disposition: EvidenceDisposition,
        dimensions: Iterable[DimensionSemanticLabel] = (),
    ) -> CentralBankSemanticLabel:
        annotators = tuple(sorted({item.strip() for item in annotator_ids if item.strip()}))
        dimension_labels = tuple(sorted(dimensions, key=lambda item: item.dimension.value))
        diff_id = official_document_diff_id(diff)
        label_id = _semantic_label_id(
            diff_id=diff_id,
            family_id=diff.family_id,
            previous_version_id=diff.previous_version_id,
            current_version_id=diff.current_version_id,
            annotation_policy_version=annotation_policy_version,
            annotator_ids=annotators,
            adjudicated=adjudicated,
            adjudicator_id=adjudicator_id,
            labeled_at=labeled_at,
            direction=direction,
            disposition=disposition,
            dimensions=dimension_labels,
        )
        return cls(
            label_id=label_id,
            schema_version=SEMANTIC_LABEL_SCHEMA_VERSION,
            research_only=True,
            execution_authority=False,
            source=HUMAN_REVIEW_SOURCE,
            diff_id=diff_id,
            family_id=diff.family_id,
            previous_version_id=diff.previous_version_id,
            current_version_id=diff.current_version_id,
            annotation_policy_version=annotation_policy_version,
            annotator_ids=annotators,
            adjudicated=adjudicated,
            adjudicator_id=adjudicator_id,
            labeled_at=labeled_at,
            direction=direction,
            disposition=disposition,
            dimensions=dimension_labels,
        )


@dataclass(frozen=True, slots=True)
class SemanticConfusionCell:
    truth_direction: StanceDirection
    predicted_direction: StanceDirection
    count: int

    def __post_init__(self) -> None:
        if self.count < 1:
            raise ValueError("semantic confusion cell count must be positive")


@dataclass(frozen=True, slots=True)
class DimensionSemanticMetrics:
    dimension: PolicyDimension
    sample_size: int
    prediction_present_count: int
    exact_direction_count: int
    exact_disposition_count: int
    exact_direction_accuracy: Decimal
    exact_disposition_accuracy: Decimal

    def __post_init__(self) -> None:
        if self.sample_size < 1:
            raise ValueError("dimension semantic metrics require a positive sample")
        for count in (self.prediction_present_count, self.exact_direction_count, self.exact_disposition_count):
            if not 0 <= count <= self.sample_size:
                raise ValueError("dimension semantic metric count is outside its sample")
        for rate in (self.exact_direction_accuracy, self.exact_disposition_accuracy):
            _validate_rate(rate, "dimension semantic accuracy")


@dataclass(frozen=True, slots=True)
class SemanticCohortMetrics:
    institution: str
    document_type: str
    family_id: str
    sample_size: int
    exact_direction_accuracy: Decimal
    exact_disposition_accuracy: Decimal
    abstention_rate: Decimal
    false_direction_rate_when_called: Decimal | None

    def __post_init__(self) -> None:
        if not self.institution.strip() or not self.document_type.strip() or not self.family_id.strip():
            raise ValueError("semantic cohort identity is required")
        if self.sample_size < 1:
            raise ValueError("semantic cohort sample must be positive")
        for rate in (self.exact_direction_accuracy, self.exact_disposition_accuracy, self.abstention_rate):
            _validate_rate(rate, "semantic cohort rate")
        _validate_optional_rate(self.false_direction_rate_when_called, "semantic cohort false-direction rate")


@dataclass(frozen=True, slots=True)
class SemanticEvaluationReport:
    report_id: str
    schema_version: str
    research_only: bool
    execution_authority: bool
    implementation_version: str
    stance_ruleset_version: str
    annotation_policy_version: str
    total_label_records: int
    adjudicated_label_records: int
    unadjudicated_label_records: int
    evaluated_labels: int
    exact_direction_accuracy: Decimal
    exact_disposition_accuracy: Decimal
    abstention_rate: Decimal
    directional_truth_count: int
    directional_truth_coverage: Decimal | None
    directional_truth_exact_recall: Decimal | None
    directional_call_count: int
    false_direction_rate_when_called: Decimal | None
    truth_contradictory_count: int
    contradiction_recall: Decimal | None
    truth_ambiguous_disposition_count: int
    ambiguous_disposition_recall: Decimal | None
    confusion: tuple[SemanticConfusionCell, ...]
    dimensions: tuple[DimensionSemanticMetrics, ...]
    cohorts: tuple[SemanticCohortMetrics, ...]
    evaluated_label_ids: tuple[str, ...]
    excluded_unadjudicated_label_ids: tuple[str, ...]

    def __post_init__(self) -> None:
        if self.schema_version != SEMANTIC_EVALUATION_SCHEMA_VERSION:
            raise ValueError("unsupported semantic evaluation schema")
        if self.research_only is not True or self.execution_authority is not False:
            raise ValueError("semantic evaluation must remain research-only")
        if not self.implementation_version.strip() or not self.stance_ruleset_version.strip() or not self.annotation_policy_version.strip():
            raise ValueError("semantic evaluation implementation/policy identity is required")
        if self.total_label_records != self.adjudicated_label_records + self.unadjudicated_label_records:
            raise ValueError("semantic evaluation label denominator is inconsistent")
        if self.evaluated_labels != self.adjudicated_label_records or self.evaluated_labels < 1:
            raise ValueError("semantic evaluation must evaluate every adjudicated label")
        if len(self.evaluated_label_ids) != self.evaluated_labels:
            raise ValueError("semantic evaluation label IDs do not match evaluated sample")
        if len(self.excluded_unadjudicated_label_ids) != self.unadjudicated_label_records:
            raise ValueError("semantic evaluation unadjudicated exclusions are inconsistent")
        for rate in (self.exact_direction_accuracy, self.exact_disposition_accuracy, self.abstention_rate):
            _validate_rate(rate, "semantic evaluation rate")
        _validate_optional_rate(self.directional_truth_coverage, "directional truth coverage")
        _validate_optional_rate(self.directional_truth_exact_recall, "directional truth exact recall")
        _validate_optional_rate(self.false_direction_rate_when_called, "false direction rate")
        _validate_optional_rate(self.contradiction_recall, "contradiction recall")
        _validate_optional_rate(self.ambiguous_disposition_recall, "ambiguous disposition recall")
        if self.report_id != _semantic_report_id(
            implementation_version=self.implementation_version,
            stance_ruleset_version=self.stance_ruleset_version,
            annotation_policy_version=self.annotation_policy_version,
            total_label_records=self.total_label_records,
            adjudicated_label_records=self.adjudicated_label_records,
            unadjudicated_label_records=self.unadjudicated_label_records,
            evaluated_labels=self.evaluated_labels,
            exact_direction_accuracy=self.exact_direction_accuracy,
            exact_disposition_accuracy=self.exact_disposition_accuracy,
            abstention_rate=self.abstention_rate,
            directional_truth_count=self.directional_truth_count,
            directional_truth_coverage=self.directional_truth_coverage,
            directional_truth_exact_recall=self.directional_truth_exact_recall,
            directional_call_count=self.directional_call_count,
            false_direction_rate_when_called=self.false_direction_rate_when_called,
            truth_contradictory_count=self.truth_contradictory_count,
            contradiction_recall=self.contradiction_recall,
            truth_ambiguous_disposition_count=self.truth_ambiguous_disposition_count,
            ambiguous_disposition_recall=self.ambiguous_disposition_recall,
            confusion=self.confusion,
            dimensions=self.dimensions,
            cohorts=self.cohorts,
            evaluated_label_ids=self.evaluated_label_ids,
            excluded_unadjudicated_label_ids=self.excluded_unadjudicated_label_ids,
        ):
            raise ValueError("semantic evaluation report ID does not match its evidence payload")


@dataclass(frozen=True, slots=True)
class _EvaluatedCase:
    label: CentralBankSemanticLabel
    current: OfficialDocumentVersion
    predicted_direction: StanceDirection
    predicted_disposition: EvidenceDisposition
    predicted_dimensions: Mapping[PolicyDimension, tuple[StanceDirection, EvidenceDisposition]]


def official_document_diff_id(diff: OfficialDocumentDiff) -> str:
    payload = {
        "family_id": diff.family_id,
        "previous_version_id": diff.previous_version_id,
        "current_version_id": diff.current_version_id,
        "added": [
            {"side": item.side, "paragraph_index": item.paragraph_index, "text_sha256": item.text_sha256}
            for item in diff.added
        ],
        "removed": [
            {"side": item.side, "paragraph_index": item.paragraph_index, "text_sha256": item.text_sha256}
            for item in diff.removed
        ],
    }
    return hashlib.sha256(_canonical_json(payload)).hexdigest()


def evaluate_semantic_labels(
    labels: Iterable[CentralBankSemanticLabel],
    versions: Iterable[OfficialDocumentVersion],
) -> SemanticEvaluationReport:
    records = tuple(labels)
    if not records:
        raise ValueError("semantic evaluation requires a non-empty human label corpus")
    if len({item.label_id for item in records}) != len(records):
        raise ValueError("semantic label corpus cannot contain duplicate label IDs")
    version_records = tuple(versions)
    version_by_id = {item.version_id: item for item in version_records}
    if len(version_by_id) != len(version_records):
        raise ValueError("semantic evaluation document versions cannot repeat version IDs")

    adjudicated = tuple(item for item in records if item.adjudicated)
    unadjudicated = tuple(item for item in records if not item.adjudicated)
    if not adjudicated:
        raise ValueError("semantic evaluation requires at least one adjudicated human label")
    if len({item.diff_id for item in adjudicated}) != len(adjudicated):
        raise ValueError("semantic evaluation cannot contain multiple adjudicated labels for one document diff")
    policies = {item.annotation_policy_version for item in adjudicated}
    if len(policies) != 1:
        raise ValueError("semantic evaluation cannot mix adjudicated annotation policy versions")
    annotation_policy_version = next(iter(policies))

    cases: list[_EvaluatedCase] = []
    for label in adjudicated:
        current = version_by_id.get(label.current_version_id)
        previous = version_by_id.get(label.previous_version_id)
        if current is None or previous is None:
            raise ValueError("semantic label references a document version absent from the evaluation corpus")
        if current.family_id != label.family_id or previous.family_id != label.family_id:
            raise ValueError("semantic label family does not match source document lineage")
        if current.predecessor_version_id != previous.version_id:
            raise ValueError("semantic label previous/current versions are not an explicit predecessor pair")
        diff = compare_document_versions(previous, current)
        if official_document_diff_id(diff) != label.diff_id:
            raise ValueError("semantic label diff ID does not match reconstructed source-backed document evidence")
        prediction = extract_central_bank_stance(diff)
        if prediction.ruleset_version != STANCE_RULESET_VERSION:
            raise ValueError("semantic evaluation stance ruleset identity drifted unexpectedly")
        cases.append(
            _EvaluatedCase(
                label=label,
                current=current,
                predicted_direction=prediction.direction,
                predicted_disposition=prediction.disposition,
                predicted_dimensions={
                    item.dimension: (item.direction, item.disposition)
                    for item in prediction.dimensions
                },
            )
        )
    cases.sort(key=lambda item: (item.current.available_at, item.label.label_id))

    total = len(cases)
    exact_direction_count = sum(item.predicted_direction is item.label.direction for item in cases)
    exact_disposition_count = sum(item.predicted_disposition is item.label.disposition for item in cases)
    abstention_count = sum(item.predicted_disposition is EvidenceDisposition.ABSTAINED for item in cases)
    truth_directional = [item for item in cases if item.label.direction in _DIRECTIONAL]
    directional_truth_calls = [item for item in truth_directional if item.predicted_direction in _DIRECTIONAL]
    directional_truth_exact = [item for item in truth_directional if item.predicted_direction is item.label.direction]
    directional_calls = [item for item in cases if item.predicted_direction in _DIRECTIONAL]
    false_directional_calls = [item for item in directional_calls if item.predicted_direction is not item.label.direction]
    truth_contradictory = [item for item in cases if item.label.direction is StanceDirection.CONTRADICTORY]
    truth_ambiguous = [item for item in cases if item.label.disposition is EvidenceDisposition.AMBIGUOUS]

    confusion_counts: dict[tuple[StanceDirection, StanceDirection], int] = {}
    for case in cases:
        key = (case.label.direction, case.predicted_direction)
        confusion_counts[key] = confusion_counts.get(key, 0) + 1
    confusion = tuple(
        SemanticConfusionCell(truth, predicted, count)
        for (truth, predicted), count in sorted(confusion_counts.items(), key=lambda item: (item[0][0].value, item[0][1].value))
    )
    dimensions = _dimension_metrics(cases)
    cohorts = _cohort_metrics(cases)
    evaluated_ids = tuple(item.label.label_id for item in cases)
    excluded_ids = tuple(sorted(item.label_id for item in unadjudicated))

    exact_direction_accuracy = _ratio(exact_direction_count, total)
    exact_disposition_accuracy = _ratio(exact_disposition_count, total)
    abstention_rate = _ratio(abstention_count, total)
    directional_truth_coverage = _optional_ratio(len(directional_truth_calls), len(truth_directional))
    directional_truth_exact_recall = _optional_ratio(len(directional_truth_exact), len(truth_directional))
    false_direction_rate_when_called = _optional_ratio(len(false_directional_calls), len(directional_calls))
    contradiction_recall = _optional_ratio(
        sum(item.predicted_direction is StanceDirection.CONTRADICTORY for item in truth_contradictory),
        len(truth_contradictory),
    )
    ambiguous_disposition_recall = _optional_ratio(
        sum(item.predicted_disposition is EvidenceDisposition.AMBIGUOUS for item in truth_ambiguous),
        len(truth_ambiguous),
    )
    report_id = _semantic_report_id(
        implementation_version=__version__,
        stance_ruleset_version=STANCE_RULESET_VERSION,
        annotation_policy_version=annotation_policy_version,
        total_label_records=len(records),
        adjudicated_label_records=len(adjudicated),
        unadjudicated_label_records=len(unadjudicated),
        evaluated_labels=total,
        exact_direction_accuracy=exact_direction_accuracy,
        exact_disposition_accuracy=exact_disposition_accuracy,
        abstention_rate=abstention_rate,
        directional_truth_count=len(truth_directional),
        directional_truth_coverage=directional_truth_coverage,
        directional_truth_exact_recall=directional_truth_exact_recall,
        directional_call_count=len(directional_calls),
        false_direction_rate_when_called=false_direction_rate_when_called,
        truth_contradictory_count=len(truth_contradictory),
        contradiction_recall=contradiction_recall,
        truth_ambiguous_disposition_count=len(truth_ambiguous),
        ambiguous_disposition_recall=ambiguous_disposition_recall,
        confusion=confusion,
        dimensions=dimensions,
        cohorts=cohorts,
        evaluated_label_ids=evaluated_ids,
        excluded_unadjudicated_label_ids=excluded_ids,
    )
    return SemanticEvaluationReport(
        report_id=report_id,
        schema_version=SEMANTIC_EVALUATION_SCHEMA_VERSION,
        research_only=True,
        execution_authority=False,
        implementation_version=__version__,
        stance_ruleset_version=STANCE_RULESET_VERSION,
        annotation_policy_version=annotation_policy_version,
        total_label_records=len(records),
        adjudicated_label_records=len(adjudicated),
        unadjudicated_label_records=len(unadjudicated),
        evaluated_labels=total,
        exact_direction_accuracy=exact_direction_accuracy,
        exact_disposition_accuracy=exact_disposition_accuracy,
        abstention_rate=abstention_rate,
        directional_truth_count=len(truth_directional),
        directional_truth_coverage=directional_truth_coverage,
        directional_truth_exact_recall=directional_truth_exact_recall,
        directional_call_count=len(directional_calls),
        false_direction_rate_when_called=false_direction_rate_when_called,
        truth_contradictory_count=len(truth_contradictory),
        contradiction_recall=contradiction_recall,
        truth_ambiguous_disposition_count=len(truth_ambiguous),
        ambiguous_disposition_recall=ambiguous_disposition_recall,
        confusion=confusion,
        dimensions=dimensions,
        cohorts=cohorts,
        evaluated_label_ids=evaluated_ids,
        excluded_unadjudicated_label_ids=excluded_ids,
    )


def load_semantic_label_corpus(path: str | Path) -> tuple[CentralBankSemanticLabel, ...]:
    labels: list[CentralBankSemanticLabel] = []
    for line_number, raw_line in enumerate(Path(path).read_text(encoding="utf-8").splitlines(), start=1):
        if not raw_line.strip():
            continue
        try:
            raw = json.loads(raw_line)
        except json.JSONDecodeError as exc:
            raise ValueError(f"semantic label JSONL line {line_number} is not valid JSON") from exc
        if not isinstance(raw, dict):
            raise ValueError(f"semantic label JSONL line {line_number} must be an object")
        try:
            dimensions_raw = raw.get("dimensions", [])
            if not isinstance(dimensions_raw, list):
                raise ValueError("dimensions must be a list")
            annotators_raw = raw["annotator_ids"]
            if not isinstance(annotators_raw, list):
                raise ValueError("annotator_ids must be a list")
            label = CentralBankSemanticLabel(
                label_id=str(raw["label_id"]),
                schema_version=str(raw["schema_version"]),
                research_only=_strict_bool(raw["research_only"], "research_only"),
                execution_authority=_strict_bool(raw["execution_authority"], "execution_authority"),
                source=str(raw["source"]),
                diff_id=str(raw["diff_id"]),
                family_id=str(raw["family_id"]),
                previous_version_id=str(raw["previous_version_id"]),
                current_version_id=str(raw["current_version_id"]),
                annotation_policy_version=str(raw["annotation_policy_version"]),
                annotator_ids=tuple(str(item) for item in annotators_raw),
                adjudicated=_strict_bool(raw["adjudicated"], "adjudicated"),
                adjudicator_id=str(raw["adjudicator_id"]) if raw.get("adjudicator_id") is not None else None,
                labeled_at=datetime.fromisoformat(str(raw["labeled_at"])),
                direction=StanceDirection(raw["direction"]),
                disposition=EvidenceDisposition(raw["disposition"]),
                dimensions=tuple(
                    DimensionSemanticLabel(
                        dimension=PolicyDimension(item["dimension"]),
                        direction=StanceDirection(item["direction"]),
                        disposition=EvidenceDisposition(item["disposition"]),
                    )
                    for item in dimensions_raw
                ),
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise ValueError(f"semantic label JSONL line {line_number} is invalid: {exc}") from exc
        labels.append(label)
    if not labels:
        raise ValueError("semantic label corpus is empty")
    return tuple(labels)


def _dimension_metrics(cases: list[_EvaluatedCase]) -> tuple[DimensionSemanticMetrics, ...]:
    grouped: dict[PolicyDimension, list[tuple[DimensionSemanticLabel, tuple[StanceDirection, EvidenceDisposition] | None]]] = {}
    for case in cases:
        for truth in case.label.dimensions:
            grouped.setdefault(truth.dimension, []).append((truth, case.predicted_dimensions.get(truth.dimension)))
    result: list[DimensionSemanticMetrics] = []
    for dimension, values in sorted(grouped.items(), key=lambda item: item[0].value):
        sample = len(values)
        present = sum(prediction is not None for _, prediction in values)
        direction_matches = sum(prediction is not None and prediction[0] is truth.direction for truth, prediction in values)
        disposition_matches = sum(prediction is not None and prediction[1] is truth.disposition for truth, prediction in values)
        result.append(
            DimensionSemanticMetrics(
                dimension=dimension,
                sample_size=sample,
                prediction_present_count=present,
                exact_direction_count=direction_matches,
                exact_disposition_count=disposition_matches,
                exact_direction_accuracy=_ratio(direction_matches, sample),
                exact_disposition_accuracy=_ratio(disposition_matches, sample),
            )
        )
    return tuple(result)


def _cohort_metrics(cases: list[_EvaluatedCase]) -> tuple[SemanticCohortMetrics, ...]:
    grouped: dict[tuple[str, str, str], list[_EvaluatedCase]] = {}
    for case in cases:
        grouped.setdefault((case.current.institution, case.current.document_type, case.current.family_id), []).append(case)
    result: list[SemanticCohortMetrics] = []
    for (institution, document_type, family_id), values in sorted(grouped.items(), key=lambda item: item[0]):
        sample = len(values)
        calls = [item for item in values if item.predicted_direction in _DIRECTIONAL]
        false_calls = [item for item in calls if item.predicted_direction is not item.label.direction]
        result.append(
            SemanticCohortMetrics(
                institution=institution,
                document_type=document_type,
                family_id=family_id,
                sample_size=sample,
                exact_direction_accuracy=_ratio(sum(item.predicted_direction is item.label.direction for item in values), sample),
                exact_disposition_accuracy=_ratio(sum(item.predicted_disposition is item.label.disposition for item in values), sample),
                abstention_rate=_ratio(sum(item.predicted_disposition is EvidenceDisposition.ABSTAINED for item in values), sample),
                false_direction_rate_when_called=_optional_ratio(len(false_calls), len(calls)),
            )
        )
    return tuple(result)


def _semantic_label_id(
    *,
    diff_id: str,
    family_id: str,
    previous_version_id: str,
    current_version_id: str,
    annotation_policy_version: str,
    annotator_ids: tuple[str, ...],
    adjudicated: bool,
    adjudicator_id: str | None,
    labeled_at: datetime,
    direction: StanceDirection,
    disposition: EvidenceDisposition,
    dimensions: tuple[DimensionSemanticLabel, ...],
) -> str:
    payload = {
        "schema_version": SEMANTIC_LABEL_SCHEMA_VERSION,
        "source": HUMAN_REVIEW_SOURCE,
        "diff_id": diff_id,
        "family_id": family_id,
        "previous_version_id": previous_version_id,
        "current_version_id": current_version_id,
        "annotation_policy_version": annotation_policy_version,
        "annotator_ids": list(annotator_ids),
        "adjudicated": adjudicated,
        "adjudicator_id": adjudicator_id,
        "labeled_at": labeled_at.isoformat(),
        "direction": direction.value,
        "disposition": disposition.value,
        "dimensions": [
            {"dimension": item.dimension.value, "direction": item.direction.value, "disposition": item.disposition.value}
            for item in dimensions
        ],
    }
    return hashlib.sha256(_canonical_json(payload)).hexdigest()


def _semantic_report_id(
    *,
    implementation_version: str,
    stance_ruleset_version: str,
    annotation_policy_version: str,
    total_label_records: int,
    adjudicated_label_records: int,
    unadjudicated_label_records: int,
    evaluated_labels: int,
    exact_direction_accuracy: Decimal,
    exact_disposition_accuracy: Decimal,
    abstention_rate: Decimal,
    directional_truth_count: int,
    directional_truth_coverage: Decimal | None,
    directional_truth_exact_recall: Decimal | None,
    directional_call_count: int,
    false_direction_rate_when_called: Decimal | None,
    truth_contradictory_count: int,
    contradiction_recall: Decimal | None,
    truth_ambiguous_disposition_count: int,
    ambiguous_disposition_recall: Decimal | None,
    confusion: tuple[SemanticConfusionCell, ...],
    dimensions: tuple[DimensionSemanticMetrics, ...],
    cohorts: tuple[SemanticCohortMetrics, ...],
    evaluated_label_ids: tuple[str, ...],
    excluded_unadjudicated_label_ids: tuple[str, ...],
) -> str:
    payload = {
        "schema_version": SEMANTIC_EVALUATION_SCHEMA_VERSION,
        "research_only": True,
        "execution_authority": False,
        "implementation_version": implementation_version,
        "stance_ruleset_version": stance_ruleset_version,
        "annotation_policy_version": annotation_policy_version,
        "total_label_records": total_label_records,
        "adjudicated_label_records": adjudicated_label_records,
        "unadjudicated_label_records": unadjudicated_label_records,
        "evaluated_labels": evaluated_labels,
        "exact_direction_accuracy": str(exact_direction_accuracy),
        "exact_disposition_accuracy": str(exact_disposition_accuracy),
        "abstention_rate": str(abstention_rate),
        "directional_truth_count": directional_truth_count,
        "directional_truth_coverage": _decimal_or_none(directional_truth_coverage),
        "directional_truth_exact_recall": _decimal_or_none(directional_truth_exact_recall),
        "directional_call_count": directional_call_count,
        "false_direction_rate_when_called": _decimal_or_none(false_direction_rate_when_called),
        "truth_contradictory_count": truth_contradictory_count,
        "contradiction_recall": _decimal_or_none(contradiction_recall),
        "truth_ambiguous_disposition_count": truth_ambiguous_disposition_count,
        "ambiguous_disposition_recall": _decimal_or_none(ambiguous_disposition_recall),
        "confusion": [
            {"truth_direction": item.truth_direction.value, "predicted_direction": item.predicted_direction.value, "count": item.count}
            for item in confusion
        ],
        "dimensions": [
            {
                "dimension": item.dimension.value,
                "sample_size": item.sample_size,
                "prediction_present_count": item.prediction_present_count,
                "exact_direction_count": item.exact_direction_count,
                "exact_disposition_count": item.exact_disposition_count,
                "exact_direction_accuracy": str(item.exact_direction_accuracy),
                "exact_disposition_accuracy": str(item.exact_disposition_accuracy),
            }
            for item in dimensions
        ],
        "cohorts": [
            {
                "institution": item.institution,
                "document_type": item.document_type,
                "family_id": item.family_id,
                "sample_size": item.sample_size,
                "exact_direction_accuracy": str(item.exact_direction_accuracy),
                "exact_disposition_accuracy": str(item.exact_disposition_accuracy),
                "abstention_rate": str(item.abstention_rate),
                "false_direction_rate_when_called": _decimal_or_none(item.false_direction_rate_when_called),
            }
            for item in cohorts
        ],
        "evaluated_label_ids": list(evaluated_label_ids),
        "excluded_unadjudicated_label_ids": list(excluded_unadjudicated_label_ids),
    }
    return hashlib.sha256(_canonical_json(payload)).hexdigest()


def _validate_direction_disposition(direction: StanceDirection, disposition: EvidenceDisposition, prefix: str) -> None:
    if direction is StanceDirection.CONTRADICTORY and disposition is not EvidenceDisposition.CONTRADICTORY:
        raise ValueError(f"{prefix} contradictory direction requires contradictory disposition")
    if disposition is EvidenceDisposition.CONTRADICTORY and direction is not StanceDirection.CONTRADICTORY:
        raise ValueError(f"{prefix} contradictory disposition requires contradictory direction")
    if disposition is EvidenceDisposition.ABSTAINED and direction is not StanceDirection.NEUTRAL:
        raise ValueError(f"{prefix} abstained disposition requires neutral direction")


def _canonical_json(value: object) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def _ratio(numerator: int, denominator: int) -> Decimal:
    if denominator < 1 or numerator < 0 or numerator > denominator:
        raise ValueError("semantic evaluation ratio denominator/count is invalid")
    return Decimal(numerator) / Decimal(denominator)


def _optional_ratio(numerator: int, denominator: int) -> Decimal | None:
    return None if denominator == 0 else _ratio(numerator, denominator)


def _validate_rate(value: Decimal, name: str) -> None:
    if not Decimal("0") <= value <= Decimal("1"):
        raise ValueError(f"{name} must be in [0,1]")


def _validate_optional_rate(value: Decimal | None, name: str) -> None:
    if value is not None:
        _validate_rate(value, name)


def _decimal_or_none(value: Decimal | None) -> str | None:
    return str(value) if value is not None else None


def _strict_bool(value: object, name: str) -> bool:
    if not isinstance(value, bool):
        raise ValueError(f"{name} must be a JSON boolean")
    return value


def _require_sha256(value: str, name: str) -> None:
    if len(value) != 64:
        raise ValueError(f"{name} must be a SHA-256 hex digest")
    try:
        int(value, 16)
    except ValueError as exc:
        raise ValueError(f"{name} must be a SHA-256 hex digest") from exc
