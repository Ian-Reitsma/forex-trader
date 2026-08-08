from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from decimal import Decimal
from typing import Iterable, Mapping

from forex_trader.infrastructure.official_document_repository import OfficialDocumentRepository
from forex_trader.intelligence.official_documents import compare_document_versions
from forex_trader.research.central_bank_stance import (
    STANCE_RULESET_VERSION,
    CentralBankStanceEvidence,
    EvidenceDisposition,
    PolicyDimension,
    StanceDirection,
    extract_central_bank_stance,
)


STANCE_LABEL_SCHEMA_VERSION = "central-bank-stance-label-v1"


@dataclass(frozen=True, slots=True)
class ExpectedDimensionLabel:
    dimension: PolicyDimension
    direction: StanceDirection

    def __post_init__(self) -> None:
        if self.direction not in {
            StanceDirection.HAWKISH,
            StanceDirection.DOVISH,
            StanceDirection.NEUTRAL,
            StanceDirection.CONTRADICTORY,
        }:
            raise ValueError("expected dimension direction is invalid")


@dataclass(frozen=True, slots=True)
class StanceEvaluationLabel:
    family_id: str
    previous_version_id: str
    current_version_id: str
    expected_direction: StanceDirection
    expected_disposition: EvidenceDisposition
    label_source_id: str
    dimensions: tuple[ExpectedDimensionLabel, ...] = ()
    schema_version: str = STANCE_LABEL_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if not self.family_id.strip() or not self.label_source_id.strip():
            raise ValueError("stance evaluation label family_id and label_source_id are required")
        _require_sha256(self.previous_version_id, "previous_version_id")
        _require_sha256(self.current_version_id, "current_version_id")
        if self.previous_version_id == self.current_version_id:
            raise ValueError("stance evaluation label must compare two different document versions")
        if self.schema_version != STANCE_LABEL_SCHEMA_VERSION:
            raise ValueError(f"unsupported stance label schema_version {self.schema_version!r}")
        dimensions = [item.dimension for item in self.dimensions]
        if len(set(dimensions)) != len(dimensions):
            raise ValueError("stance evaluation dimension labels must be unique")

    @property
    def label_id(self) -> str:
        payload = {
            "schema_version": self.schema_version,
            "family_id": self.family_id,
            "previous_version_id": self.previous_version_id,
            "current_version_id": self.current_version_id,
            "expected_direction": self.expected_direction.value,
            "expected_disposition": self.expected_disposition.value,
            "label_source_id": self.label_source_id,
            "dimensions": [
                {"dimension": item.dimension.value, "direction": item.direction.value}
                for item in sorted(self.dimensions, key=lambda value: value.dimension.value)
            ],
        }
        return _sha256_json(payload)


@dataclass(frozen=True, slots=True)
class StanceEvaluationDataset:
    labels: tuple[StanceEvaluationLabel, ...]

    def __post_init__(self) -> None:
        if not self.labels:
            raise ValueError("stance evaluation dataset cannot be empty")
        pair_keys = [
            (item.family_id, item.previous_version_id, item.current_version_id)
            for item in self.labels
        ]
        if len(set(pair_keys)) != len(pair_keys):
            raise ValueError("stance evaluation dataset cannot contain duplicate version pairs")
        label_ids = [item.label_id for item in self.labels]
        if len(set(label_ids)) != len(label_ids):
            raise ValueError("stance evaluation dataset cannot contain duplicate labels")

    @property
    def dataset_id(self) -> str:
        payload = {
            "schema_version": STANCE_LABEL_SCHEMA_VERSION,
            "label_ids": sorted(item.label_id for item in self.labels),
        }
        return _sha256_json(payload)


@dataclass(frozen=True, slots=True)
class StanceEvaluationCase:
    label: StanceEvaluationLabel
    prediction: CentralBankStanceEvidence
    direction_correct: bool
    disposition_correct: bool
    exact_correct: bool
    false_directional: bool
    dimension_correct: int
    dimension_labeled: int


@dataclass(frozen=True, slots=True)
class StanceEvaluationCohort:
    cohort: str
    count: int
    coverage: Decimal
    exact_accuracy: Decimal
    directional_accuracy_when_covered: Decimal | None
    false_directional_rate: Decimal
    contradiction_recall: Decimal | None


@dataclass(frozen=True, slots=True)
class StanceEvaluationReport:
    research_only: bool
    execution_authority: bool
    label_schema_version: str
    ruleset_version: str
    dataset_id: str
    total_labels: int
    covered_predictions: int
    abstentions: int
    coverage: Decimal
    abstention_rate: Decimal
    direction_accuracy: Decimal
    disposition_accuracy: Decimal
    exact_accuracy: Decimal
    directional_accuracy_when_covered: Decimal | None
    false_directional_rate: Decimal
    contradiction_recall: Decimal | None
    dimension_accuracy: Decimal | None
    confusion: Mapping[str, Mapping[str, int]]
    cohorts: tuple[StanceEvaluationCohort, ...]
    cases: tuple[StanceEvaluationCase, ...]

    def __post_init__(self) -> None:
        if self.research_only is not True or self.execution_authority is not False:
            raise ValueError("stance evaluation report must remain research-only")
        _require_sha256(self.dataset_id, "dataset_id")
        if self.total_labels < 1 or self.covered_predictions < 0 or self.abstentions < 0:
            raise ValueError("stance evaluation counts are invalid")
        if self.covered_predictions + self.abstentions != self.total_labels:
            raise ValueError("stance evaluation covered + abstentions must equal total labels")


def evaluate_stance_dataset(
    dataset: StanceEvaluationDataset,
    repository: OfficialDocumentRepository,
) -> StanceEvaluationReport:
    cases = tuple(_evaluate_label(label, repository) for label in dataset.labels)
    covered = tuple(case for case in cases if case.prediction.disposition is not EvidenceDisposition.ABSTAINED)
    abstentions = len(cases) - len(covered)
    false_directional = sum(case.false_directional for case in cases)
    direction_correct = sum(case.direction_correct for case in cases)
    disposition_correct = sum(case.disposition_correct for case in cases)
    exact_correct = sum(case.exact_correct for case in cases)
    dimension_labeled = sum(case.dimension_labeled for case in cases)
    dimension_correct = sum(case.dimension_correct for case in cases)
    contradiction_labels = tuple(
        case for case in cases if case.label.expected_direction is StanceDirection.CONTRADICTORY
    )
    contradiction_hits = sum(
        case.prediction.direction is StanceDirection.CONTRADICTORY for case in contradiction_labels
    )
    confusion = _confusion(cases)
    cohorts = _cohorts(cases, repository)
    return StanceEvaluationReport(
        research_only=True,
        execution_authority=False,
        label_schema_version=STANCE_LABEL_SCHEMA_VERSION,
        ruleset_version=STANCE_RULESET_VERSION,
        dataset_id=dataset.dataset_id,
        total_labels=len(cases),
        covered_predictions=len(covered),
        abstentions=abstentions,
        coverage=_ratio(len(covered), len(cases)),
        abstention_rate=_ratio(abstentions, len(cases)),
        direction_accuracy=_ratio(direction_correct, len(cases)),
        disposition_accuracy=_ratio(disposition_correct, len(cases)),
        exact_accuracy=_ratio(exact_correct, len(cases)),
        directional_accuracy_when_covered=(
            _ratio(sum(case.direction_correct for case in covered), len(covered)) if covered else None
        ),
        false_directional_rate=_ratio(false_directional, len(cases)),
        contradiction_recall=(
            _ratio(contradiction_hits, len(contradiction_labels)) if contradiction_labels else None
        ),
        dimension_accuracy=(
            _ratio(dimension_correct, dimension_labeled) if dimension_labeled else None
        ),
        confusion=confusion,
        cohorts=cohorts,
        cases=cases,
    )


def load_stance_labels(path: str) -> StanceEvaluationDataset:
    labels: list[StanceEvaluationLabel] = []
    with open(path, encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, start=1):
            if not line.strip():
                continue
            try:
                raw = json.loads(line)
            except json.JSONDecodeError as exc:
                raise ValueError(f"invalid JSON on stance label line {line_number}") from exc
            if not isinstance(raw, dict):
                raise ValueError(f"stance label line {line_number} must be a JSON object")
            labels.append(_label_from_mapping(raw, line_number))
    return StanceEvaluationDataset(tuple(labels))


def _evaluate_label(
    label: StanceEvaluationLabel,
    repository: OfficialDocumentRepository,
) -> StanceEvaluationCase:
    previous = repository.get(label.previous_version_id)
    current = repository.get(label.current_version_id)
    if previous is None or current is None:
        raise ValueError(f"stance label {label.label_id} references missing document version evidence")
    if previous.family_id != label.family_id or current.family_id != label.family_id:
        raise ValueError(f"stance label {label.label_id} family_id does not match persisted document versions")
    if current.predecessor_version_id != previous.version_id:
        raise ValueError(f"stance label {label.label_id} does not reference an adjacent persisted predecessor pair")
    prediction = extract_central_bank_stance(compare_document_versions(previous, current))
    direction_correct = prediction.direction is label.expected_direction
    disposition_correct = prediction.disposition is label.expected_disposition
    predicted_directional = prediction.direction in {StanceDirection.HAWKISH, StanceDirection.DOVISH}
    expected_nondirectional = label.expected_direction in {StanceDirection.NEUTRAL, StanceDirection.CONTRADICTORY}
    false_directional = predicted_directional and expected_nondirectional
    predicted_dimensions = {item.dimension: item.direction for item in prediction.dimensions}
    dimension_correct = sum(
        predicted_dimensions.get(item.dimension, StanceDirection.NEUTRAL) is item.direction
        for item in label.dimensions
    )
    return StanceEvaluationCase(
        label=label,
        prediction=prediction,
        direction_correct=direction_correct,
        disposition_correct=disposition_correct,
        exact_correct=direction_correct and disposition_correct,
        false_directional=false_directional,
        dimension_correct=dimension_correct,
        dimension_labeled=len(label.dimensions),
    )


def _cohorts(
    cases: tuple[StanceEvaluationCase, ...],
    repository: OfficialDocumentRepository,
) -> tuple[StanceEvaluationCohort, ...]:
    groups: dict[str, list[StanceEvaluationCase]] = {}
    for case in cases:
        current = repository.get(case.label.current_version_id)
        if current is None:
            raise ValueError("stance evaluation cohort cannot resolve current document version")
        for key in (
            f"family={case.label.family_id}",
            f"institution={current.institution}",
            f"document_type={current.document_type}",
        ):
            groups.setdefault(key, []).append(case)
    return tuple(_cohort(key, tuple(groups[key])) for key in sorted(groups))


def _cohort(name: str, cases: tuple[StanceEvaluationCase, ...]) -> StanceEvaluationCohort:
    covered = tuple(case for case in cases if case.prediction.disposition is not EvidenceDisposition.ABSTAINED)
    contradiction_labels = tuple(
        case for case in cases if case.label.expected_direction is StanceDirection.CONTRADICTORY
    )
    return StanceEvaluationCohort(
        cohort=name,
        count=len(cases),
        coverage=_ratio(len(covered), len(cases)),
        exact_accuracy=_ratio(sum(case.exact_correct for case in cases), len(cases)),
        directional_accuracy_when_covered=(
            _ratio(sum(case.direction_correct for case in covered), len(covered)) if covered else None
        ),
        false_directional_rate=_ratio(sum(case.false_directional for case in cases), len(cases)),
        contradiction_recall=(
            _ratio(
                sum(case.prediction.direction is StanceDirection.CONTRADICTORY for case in contradiction_labels),
                len(contradiction_labels),
            )
            if contradiction_labels
            else None
        ),
    )


def _confusion(cases: tuple[StanceEvaluationCase, ...]) -> dict[str, dict[str, int]]:
    directions = tuple(item.value for item in StanceDirection)
    table = {expected: {predicted: 0 for predicted in directions} for expected in directions}
    for case in cases:
        table[case.label.expected_direction.value][case.prediction.direction.value] += 1
    return table


def _label_from_mapping(raw: Mapping[str, object], line_number: int) -> StanceEvaluationLabel:
    try:
        dimensions_raw = raw.get("dimensions", [])
        if not isinstance(dimensions_raw, list):
            raise ValueError("dimensions must be an array")
        dimensions: list[ExpectedDimensionLabel] = []
        for index, item in enumerate(dimensions_raw):
            if not isinstance(item, Mapping):
                raise ValueError(f"dimensions[{index}] must be an object")
            dimensions.append(
                ExpectedDimensionLabel(
                    dimension=PolicyDimension(str(item["dimension"])),
                    direction=StanceDirection(str(item["direction"])),
                )
            )
        return StanceEvaluationLabel(
            family_id=str(raw["family_id"]),
            previous_version_id=str(raw["previous_version_id"]),
            current_version_id=str(raw["current_version_id"]),
            expected_direction=StanceDirection(str(raw["expected_direction"])),
            expected_disposition=EvidenceDisposition(str(raw["expected_disposition"])),
            label_source_id=str(raw["label_source_id"]),
            dimensions=tuple(dimensions),
            schema_version=str(raw.get("schema_version", STANCE_LABEL_SCHEMA_VERSION)),
        )
    except (KeyError, ValueError) as exc:
        raise ValueError(f"invalid stance label on line {line_number}: {exc}") from exc


def _ratio(numerator: int, denominator: int) -> Decimal:
    if denominator < 1:
        raise ValueError("stance evaluation ratio denominator must be positive")
    return Decimal(numerator) / Decimal(denominator)


def _sha256_json(payload: object) -> str:
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(encoded).hexdigest()


def _require_sha256(value: str, name: str) -> None:
    if len(value) != 64:
        raise ValueError(f"{name} must be a SHA-256 hex digest")
    try:
        int(value, 16)
    except ValueError as exc:
        raise ValueError(f"{name} must be a SHA-256 hex digest") from exc
