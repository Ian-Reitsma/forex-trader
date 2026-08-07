from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from decimal import Decimal
from pathlib import Path
from random import Random
from typing import Iterable

from forex_trader.research.ablations import (
    AblationVariant,
    MaturedAblationOutcome,
    paired_ablation_evidence,
)
from forex_trader.research.phase_d import paired_bootstrap_mean_interval


INDIVIDUAL_INTERVAL_SCOPE = "individual_component"
SIMULTANEOUS_INTERVAL_SCOPE = "simultaneous_familywise"
INDIVIDUAL_BOOTSTRAP_METHOD = "paired_bootstrap_mean_percentile"
SIMULTANEOUS_BOOTSTRAP_METHOD = "paired_bootstrap_max_deviation_simultaneous"


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
    interval_scope: str = INDIVIDUAL_INTERVAL_SCOPE
    multiple_testing_method: str = INDIVIDUAL_BOOTSTRAP_METHOD
    familywise_confidence: Decimal | None = None
    family_size: int | None = None

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
        if self.interval_scope == SIMULTANEOUS_INTERVAL_SCOPE:
            if self.multiple_testing_method != SIMULTANEOUS_BOOTSTRAP_METHOD:
                raise ValueError("simultaneous family-wise evidence requires max-deviation bootstrap method")
            if self.familywise_confidence is None or not Decimal("0") < self.familywise_confidence < Decimal("1"):
                raise ValueError("simultaneous family-wise evidence requires familywise_confidence in (0,1)")
            if self.family_size is None or self.family_size < 2:
                raise ValueError("simultaneous family-wise evidence requires family_size >= 2")
            if self.confidence != self.familywise_confidence:
                raise ValueError("simultaneous confidence must equal familywise_confidence")
        elif self.familywise_confidence is not None or self.family_size is not None:
            raise ValueError("individual intervals cannot claim family-wise coverage")

    @property
    def component_increment_r(self) -> Decimal:
        return self.full_expectancy_r - self.ablated_expectancy_r


@dataclass(frozen=True, slots=True)
class _PairedDeltaFamily:
    base_by_variant: dict[AblationVariant, tuple[Decimal, Decimal, int, str]]
    deltas_by_variant: dict[AblationVariant, tuple[Decimal, ...]]
    sample_size: int


def paired_ablation_uncertainty_evidence(
    outcomes: Iterable[MaturedAblationOutcome],
    *,
    primary_dataset_id: str,
    confidence: Decimal = Decimal("0.90"),
    bootstrap_iterations: int = 2000,
    bootstrap_seed: int = 20260807,
) -> tuple[PairedAblationUncertaintyEvidence, ...]:
    """Estimate individual component deltas with paired percentile bootstrap intervals.

    This remains available for diagnostics/backward compatibility. Promotion-grade evidence
    across the five predefined components should use ``paired_ablation_familywise_evidence``.
    """
    family = _paired_delta_family(outcomes, primary_dataset_id=primary_dataset_id)
    results: list[PairedAblationUncertaintyEvidence] = []
    for variant, deltas in family.deltas_by_variant.items():
        full_expectancy, ablated_expectancy, sample_size, dataset_id = family.base_by_variant[variant]
        lower, upper = paired_bootstrap_mean_interval(
            deltas,
            confidence=confidence,
            iterations=bootstrap_iterations,
            seed=bootstrap_seed,
        )
        results.append(
            _evidence_row(
                variant=variant,
                deltas=deltas,
                full_expectancy=full_expectancy,
                ablated_expectancy=ablated_expectancy,
                sample_size=sample_size,
                dataset_id=dataset_id,
                lower=lower,
                upper=upper,
                confidence=confidence,
                bootstrap_iterations=bootstrap_iterations,
                bootstrap_seed=bootstrap_seed,
            )
        )
    return tuple(results)


def paired_ablation_familywise_evidence(
    outcomes: Iterable[MaturedAblationOutcome],
    *,
    primary_dataset_id: str,
    familywise_confidence: Decimal = Decimal("0.90"),
    bootstrap_iterations: int = 5000,
    bootstrap_seed: int = 20260807,
) -> tuple[PairedAblationUncertaintyEvidence, ...]:
    """Build simultaneous paired confidence bands across all component ablations.

    Every bootstrap iteration resamples one common snapshot-index vector and applies it to
    all component delta series. The maximum absolute centered mean deviation across the
    family is recorded. Its family-wise confidence quantile becomes one simultaneous
    critical width around every observed component mean. This preserves cross-component
    correlation because the same frozen snapshots are resampled together.
    """
    if not Decimal("0") < familywise_confidence < Decimal("1"):
        raise ValueError("familywise_confidence must be in (0,1)")
    if bootstrap_iterations < 100:
        raise ValueError("bootstrap_iterations must be at least 100")
    family = _paired_delta_family(outcomes, primary_dataset_id=primary_dataset_id)
    variants = tuple(family.deltas_by_variant)
    family_size = len(variants)
    if family_size < 2:
        raise ValueError("family-wise ablation evidence requires at least two components")
    observed = {
        variant: _mean(family.deltas_by_variant[variant])
        for variant in variants
    }
    random = Random(bootstrap_seed)
    maximum_deviations: list[Decimal] = []
    for _ in range(bootstrap_iterations):
        indices = tuple(random.randrange(family.sample_size) for _ in range(family.sample_size))
        iteration_max = Decimal("0")
        for variant in variants:
            deltas = family.deltas_by_variant[variant]
            bootstrap_mean = sum((deltas[index] for index in indices), Decimal("0")) / Decimal(family.sample_size)
            iteration_max = max(iteration_max, abs(bootstrap_mean - observed[variant]))
        maximum_deviations.append(iteration_max)
    critical_width = _quantile(tuple(sorted(maximum_deviations)), familywise_confidence)

    results: list[PairedAblationUncertaintyEvidence] = []
    for variant in variants:
        deltas = family.deltas_by_variant[variant]
        full_expectancy, ablated_expectancy, sample_size, dataset_id = family.base_by_variant[variant]
        center = observed[variant]
        results.append(
            _evidence_row(
                variant=variant,
                deltas=deltas,
                full_expectancy=full_expectancy,
                ablated_expectancy=ablated_expectancy,
                sample_size=sample_size,
                dataset_id=dataset_id,
                lower=center - critical_width,
                upper=center + critical_width,
                confidence=familywise_confidence,
                bootstrap_iterations=bootstrap_iterations,
                bootstrap_seed=bootstrap_seed,
                interval_scope=SIMULTANEOUS_INTERVAL_SCOPE,
                multiple_testing_method=SIMULTANEOUS_BOOTSTRAP_METHOD,
                familywise_confidence=familywise_confidence,
                family_size=family_size,
            )
        )
    return tuple(results)


def write_paired_ablation_uncertainty_evidence(
    path: str | Path,
    evidence: Iterable[PairedAblationUncertaintyEvidence],
    *,
    artifact_id: str,
) -> None:
    _validate_sha256(artifact_id, "artifact_id")
    values = tuple(evidence)
    if not values:
        raise ValueError("paired ablation uncertainty evidence cannot be empty")
    dataset_ids = {item.dataset_id for item in values}
    sample_sizes = {item.sample_size for item in values}
    full_values = {item.full_expectancy_r for item in values}
    confidences = {item.confidence for item in values}
    iterations = {item.bootstrap_iterations for item in values}
    seeds = {item.bootstrap_seed for item in values}
    scopes = {item.interval_scope for item in values}
    methods = {item.multiple_testing_method for item in values}
    familywise_confidences = {item.familywise_confidence for item in values}
    family_sizes = {item.family_size for item in values}
    if len(dataset_ids) != 1 or len(sample_sizes) != 1 or len(full_values) != 1:
        raise ValueError("paired ablation uncertainty must share dataset, denominator and full baseline")
    if len(confidences) != 1 or len(iterations) != 1 or len(seeds) != 1:
        raise ValueError("paired ablation uncertainty must share bootstrap configuration")
    if len(scopes) != 1 or len(methods) != 1 or len(familywise_confidences) != 1 or len(family_sizes) != 1:
        raise ValueError("paired ablation uncertainty must share interval-family configuration")
    payload = {
        "research_only": True,
        "execution_authority": False,
        "dataset_id": next(iter(dataset_ids)),
        "paired_artifact_id": artifact_id,
        "sample_size": next(iter(sample_sizes)),
        "uncertainty": {
            "method": next(iter(methods)),
            "interval_scope": next(iter(scopes)),
            "delta_semantics": "full_realized_r_minus_ablated_realized_r",
            "confidence": str(next(iter(confidences))),
            "familywise_confidence": (
                None if next(iter(familywise_confidences)) is None else str(next(iter(familywise_confidences)))
            ),
            "family_size": next(iter(family_sizes)),
            "bootstrap_iterations": next(iter(iterations)),
            "bootstrap_seed": next(iter(seeds)),
        },
        "ablations": [
            {
                **{
                    key: str(value) if isinstance(value, Decimal) else value
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


def _paired_delta_family(
    outcomes: Iterable[MaturedAblationOutcome],
    *,
    primary_dataset_id: str,
) -> _PairedDeltaFamily:
    rows = tuple(outcomes)
    base = paired_ablation_evidence(rows, primary_dataset_id=primary_dataset_id)
    grouped: dict[str, dict[AblationVariant, MaturedAblationOutcome]] = {}
    for row in rows:
        grouped.setdefault(row.snapshot_id, {})[row.variant] = row
    ordered_ids = tuple(sorted(grouped))
    base_by_variant: dict[AblationVariant, tuple[Decimal, Decimal, int, str]] = {}
    deltas_by_variant: dict[AblationVariant, tuple[Decimal, ...]] = {}
    sample_sizes = {item.sample_size for item in base}
    if len(sample_sizes) != 1:
        raise ValueError("paired ablation family must share one sample size")
    sample_size = next(iter(sample_sizes))
    for item in base:
        variant = AblationVariant(item.name)
        deltas = tuple(
            grouped[snapshot_id][AblationVariant.FULL].realized_r
            - grouped[snapshot_id][variant].realized_r
            for snapshot_id in ordered_ids
        )
        if len(deltas) != item.sample_size:
            raise ValueError(f"paired delta denominator mismatch for {item.name}")
        base_by_variant[variant] = (
            item.full_expectancy_r,
            item.ablated_expectancy_r,
            item.sample_size,
            item.dataset_id,
        )
        deltas_by_variant[variant] = deltas
    return _PairedDeltaFamily(base_by_variant, deltas_by_variant, sample_size)


def _evidence_row(
    *,
    variant: AblationVariant,
    deltas: tuple[Decimal, ...],
    full_expectancy: Decimal,
    ablated_expectancy: Decimal,
    sample_size: int,
    dataset_id: str,
    lower: Decimal,
    upper: Decimal,
    confidence: Decimal,
    bootstrap_iterations: int,
    bootstrap_seed: int,
    interval_scope: str = INDIVIDUAL_INTERVAL_SCOPE,
    multiple_testing_method: str = INDIVIDUAL_BOOTSTRAP_METHOD,
    familywise_confidence: Decimal | None = None,
    family_size: int | None = None,
) -> PairedAblationUncertaintyEvidence:
    return PairedAblationUncertaintyEvidence(
        name=variant.value,
        full_expectancy_r=full_expectancy,
        ablated_expectancy_r=ablated_expectancy,
        sample_size=sample_size,
        dataset_id=dataset_id,
        lower_confidence_component_increment_r=lower,
        upper_confidence_component_increment_r=upper,
        paired_wins=sum(delta > 0 for delta in deltas),
        paired_losses=sum(delta < 0 for delta in deltas),
        paired_ties=sum(delta == 0 for delta in deltas),
        confidence=confidence,
        bootstrap_iterations=bootstrap_iterations,
        bootstrap_seed=bootstrap_seed,
        interval_scope=interval_scope,
        multiple_testing_method=multiple_testing_method,
        familywise_confidence=familywise_confidence,
        family_size=family_size,
    )


def _mean(values: tuple[Decimal, ...]) -> Decimal:
    if not values:
        raise ValueError("cannot average an empty paired delta series")
    return sum(values, Decimal("0")) / Decimal(len(values))


def _quantile(values: tuple[Decimal, ...], probability: Decimal) -> Decimal:
    if not values:
        raise ValueError("cannot compute a quantile from an empty sequence")
    if probability <= 0:
        return values[0]
    if probability >= 1:
        return values[-1]
    position = probability * Decimal(len(values) - 1)
    lower_index = int(position)
    upper_index = min(lower_index + 1, len(values) - 1)
    fraction = position - Decimal(lower_index)
    return values[lower_index] + (values[upper_index] - values[lower_index]) * fraction


def _validate_sha256(value: str, name: str) -> None:
    if len(value) != 64:
        raise ValueError(f"{name} must be a SHA-256 hex digest")
    try:
        int(value, 16)
    except ValueError as exc:
        raise ValueError(f"{name} must be a SHA-256 hex digest") from exc
