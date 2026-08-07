from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from decimal import Decimal
from pathlib import Path
from typing import Iterable

from forex_trader.research.ablations import (
    AblationVariant,
    MaturedAblationOutcome,
    paired_ablation_evidence,
)
from forex_trader.research.phase_d import paired_bootstrap_mean_interval


@dataclass(frozen=True, slots=True)
class PairedAblationUncertaintyEvidence:
    """Paired full-minus-ablated component evidence with deterministic uncertainty."""

    name: str
    full_expectancy_r: Decimal
    ablated_expectancy_r: Decimal
    sample_size: int
    dataset_id: str
    lower_confidence_component_increment_r: Decimal
    upper_confidence_component_increment_r: Decimal
    paired_wins: int
    paired_losses: int
    paired_ties: int
    confidence: Decimal
    bootstrap_iterations: int
    bootstrap_seed: int

    def __post_init__(self) -> None:
        if not self.name.strip() or not self.dataset_id.strip():
            raise ValueError("ablation uncertainty name and dataset_id are required")
        if self.sample_size < 1:
            raise ValueError("ablation uncertainty sample_size must be positive")
        if not Decimal("0") < self.confidence < Decimal("1"):
            raise ValueError("ablation uncertainty confidence must be in (0,1)")
        if self.bootstrap_iterations < 100:
            raise ValueError("ablation uncertainty bootstrap_iterations must be at least 100")
        if min(self.paired_wins, self.paired_losses, self.paired_ties) < 0:
            raise ValueError("paired win/loss/tie counts cannot be negative")
        if self.paired_wins + self.paired_losses + self.paired_ties != self.sample_size:
            raise ValueError("paired win/loss/tie counts must equal sample_size")
        if self.lower_confidence_component_increment_r > self.upper_confidence_component_increment_r:
            raise ValueError("ablation uncertainty lower bound cannot exceed upper bound")

    @property
    def component_increment_r(self) -> Decimal:
        return self.full_expectancy_r - self.ablated_expectancy_r


def paired_ablation_uncertainty_evidence(
    outcomes: Iterable[MaturedAblationOutcome],
    *,
    primary_dataset_id: str,
    confidence: Decimal = Decimal("0.90"),
    bootstrap_iterations: int = 2000,
    bootstrap_seed: int = 20260807,
) -> tuple[PairedAblationUncertaintyEvidence, ...]:
    """Estimate each component's paired per-snapshot contribution with a bootstrap CI.

    Positive deltas mean the full policy beat the one-component ablation on that exact
    snapshot. The ordinary paired evidence function remains the integrity/mean authority;
    this layer adds deterministic uncertainty without changing its denominator semantics.
    """
    base = paired_ablation_evidence(outcomes, primary_dataset_id=primary_dataset_id)
    rows = tuple(outcomes)
    grouped: dict[str, dict[AblationVariant, MaturedAblationOutcome]] = {}
    for row in rows:
        grouped.setdefault(row.snapshot_id, {})[row.variant] = row
    ordered_ids = tuple(sorted(grouped))
    results: list[PairedAblationUncertaintyEvidence] = []
    for item in base:
        variant = AblationVariant(item.name)
        deltas = tuple(
            grouped[snapshot_id][AblationVariant.FULL].realized_r
            - grouped[snapshot_id][variant].realized_r
            for snapshot_id in ordered_ids
        )
        if len(deltas) != item.sample_size:
            raise ValueError(f"paired delta denominator mismatch for {item.name}")
        lower, upper = paired_bootstrap_mean_interval(
            deltas,
            confidence=confidence,
            iterations=bootstrap_iterations,
            seed=bootstrap_seed,
        )
        results.append(
            PairedAblationUncertaintyEvidence(
                name=item.name,
                full_expectancy_r=item.full_expectancy_r,
                ablated_expectancy_r=item.ablated_expectancy_r,
                sample_size=item.sample_size,
                dataset_id=item.dataset_id,
                lower_confidence_component_increment_r=lower,
                upper_confidence_component_increment_r=upper,
                paired_wins=sum(delta > 0 for delta in deltas),
                paired_losses=sum(delta < 0 for delta in deltas),
                paired_ties=sum(delta == 0 for delta in deltas),
                confidence=confidence,
                bootstrap_iterations=bootstrap_iterations,
                bootstrap_seed=bootstrap_seed,
            )
        )
    return tuple(results)


def write_paired_ablation_uncertainty_evidence(
    path: str | Path,
    evidence: Iterable[PairedAblationUncertaintyEvidence],
    *,
    artifact_id: str,
) -> None:
    values = tuple(evidence)
    if not values:
        raise ValueError("paired ablation uncertainty evidence cannot be empty")
    dataset_ids = {item.dataset_id for item in values}
    sample_sizes = {item.sample_size for item in values}
    full_values = {item.full_expectancy_r for item in values}
    confidences = {item.confidence for item in values}
    iterations = {item.bootstrap_iterations for item in values}
    seeds = {item.bootstrap_seed for item in values}
    if len(dataset_ids) != 1 or len(sample_sizes) != 1 or len(full_values) != 1:
        raise ValueError("paired ablation uncertainty must share dataset, denominator and full baseline")
    if len(confidences) != 1 or len(iterations) != 1 or len(seeds) != 1:
        raise ValueError("paired ablation uncertainty must share bootstrap configuration")
    payload = {
        "research_only": True,
        "execution_authority": False,
        "dataset_id": next(iter(dataset_ids)),
        "paired_artifact_id": artifact_id,
        "sample_size": next(iter(sample_sizes)),
        "uncertainty": {
            "method": "paired_bootstrap_mean_percentile",
            "delta_semantics": "full_realized_r_minus_ablated_realized_r",
            "confidence": str(next(iter(confidences))),
            "bootstrap_iterations": next(iter(iterations)),
            "bootstrap_seed": next(iter(seeds)),
        },
        "ablations": [
            {
                **{
                    key: (
                        str(value)
                        if isinstance(value, Decimal)
                        else value
                    )
                    for key, value in asdict(item).items()
                },
                "component_increment_r": str(item.component_increment_r),
            }
            for item in sorted(values, key=lambda item: item.name)
        ],
    }
    file_path = Path(path)
    file_path.parent.mkdir(parents=True, exist_ok=True)
    file_path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
