from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from forex_trader.research.central_bank_stance import EvidenceDisposition, StanceDirection
from forex_trader.research.central_bank_stance_evaluation import StanceEvaluationDataset


@dataclass(frozen=True, slots=True)
class StanceEvaluationBaseline:
    name: str
    direction: StanceDirection
    disposition: EvidenceDisposition
    direction_accuracy: Decimal
    exact_accuracy: Decimal
    false_directional_rate: Decimal


def trivial_stance_baselines(dataset: StanceEvaluationDataset) -> tuple[StanceEvaluationBaseline, ...]:
    return tuple(
        _baseline(dataset, name, direction, disposition)
        for name, direction, disposition in (
            ("always_abstain", StanceDirection.NEUTRAL, EvidenceDisposition.ABSTAINED),
            ("always_hawkish", StanceDirection.HAWKISH, EvidenceDisposition.SUPPORTED),
            ("always_dovish", StanceDirection.DOVISH, EvidenceDisposition.SUPPORTED),
        )
    )


def _baseline(
    dataset: StanceEvaluationDataset,
    name: str,
    direction: StanceDirection,
    disposition: EvidenceDisposition,
) -> StanceEvaluationBaseline:
    total = len(dataset.labels)
    direction_correct = sum(label.expected_direction is direction for label in dataset.labels)
    exact_correct = sum(
        label.expected_direction is direction and label.expected_disposition is disposition
        for label in dataset.labels
    )
    predicted_directional = direction in {StanceDirection.HAWKISH, StanceDirection.DOVISH}
    false_directional = sum(
        predicted_directional
        and label.expected_direction in {StanceDirection.NEUTRAL, StanceDirection.CONTRADICTORY}
        for label in dataset.labels
    )
    return StanceEvaluationBaseline(
        name=name,
        direction=direction,
        disposition=disposition,
        direction_accuracy=Decimal(direction_correct) / Decimal(total),
        exact_accuracy=Decimal(exact_correct) / Decimal(total),
        false_directional_rate=Decimal(false_directional) / Decimal(total),
    )
