from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from decimal import Decimal
from enum import Enum
from random import Random
from typing import Iterable

from forex_trader import __version__
from forex_trader.research.stance_outcomes import (
    DEFAULT_STANCE_HORIZONS_MINUTES,
    STANCE_OUTCOME_PRICE_SEMANTICS,
    StanceOutcomeDataset,
    StanceOutcomeObservation,
)


STANCE_STATISTICAL_SCHEMA_VERSION = "central-bank-stance-statistical-validation-v1"
STANCE_STATISTICAL_POLICY_VERSION = "central-bank-stance-statistical-policy-v1"
PRIMARY_HORIZON_MINUTES = 60
FAMILYWISE_CONFIDENCE = Decimal("0.90")
BOOTSTRAP_ITERATIONS = 5000
BOOTSTRAP_SEED = 20260808
CALIBRATION_NUMERATOR = 2
CALIBRATION_DENOMINATOR = 3
MIN_DIRECTIONAL_EVENTS = 24
MIN_CALIBRATION_EVENTS = 16
MIN_HOLDOUT_EVENTS = 8
MIN_OBSERVED_EVENT_FRACTION = Decimal("0.80")
FIXED_MAX_BASELINE_DELAY_SECONDS = Decimal("300")
SIMULTANEOUS_METHOD = "joint_event_bootstrap_max_deviation_simultaneous"
SPLIT_POLICY = "chronological_first_two_thirds_calibration_final_one_third_holdout"


class StanceStatisticalDisposition(str, Enum):
    INSUFFICIENT_EVIDENCE = "insufficient_evidence"
    REJECTED = "rejected"
    INFORMATIONAL_SIGNAL_CANDIDATE = "informational_signal_candidate"


@dataclass(frozen=True, slots=True)
class HorizonStatisticalBand:
    horizon_minutes: int
    sample_size: int
    mean_stance_aligned_return_bps: Decimal
    lower_simultaneous_mean_bps: Decimal
    upper_simultaneous_mean_bps: Decimal
    stance_aligned_hit_rate: Decimal

    def __post_init__(self) -> None:
        if self.horizon_minutes not in DEFAULT_STANCE_HORIZONS_MINUTES:
            raise ValueError("statistical band horizon must belong to the predeclared family")
        if self.sample_size < 1:
            raise ValueError("statistical band sample size must be positive")
        if self.lower_simultaneous_mean_bps > self.mean_stance_aligned_return_bps:
            raise ValueError("statistical band lower bound cannot exceed observed mean")
        if self.upper_simultaneous_mean_bps < self.mean_stance_aligned_return_bps:
            raise ValueError("statistical band upper bound cannot be below observed mean")
        if not Decimal("0") <= self.stance_aligned_hit_rate <= Decimal("1"):
            raise ValueError("statistical band hit rate must be in [0,1]")


@dataclass(frozen=True, slots=True)
class ChronologicalStatisticalSplit:
    name: str
    event_count: int
    first_document_available_at: str
    last_document_available_at: str
    event_ids: tuple[str, ...]
    bootstrap_seed: int
    simultaneous_critical_width_bps: Decimal
    bands: tuple[HorizonStatisticalBand, ...]

    def __post_init__(self) -> None:
        if self.name not in {"calibration", "holdout"}:
            raise ValueError("statistical split name must be calibration or holdout")
        if self.event_count < 1 or self.event_count != len(self.event_ids):
            raise ValueError("statistical split event denominator is inconsistent")
        if len(set(self.event_ids)) != len(self.event_ids):
            raise ValueError("statistical split event IDs must be unique")
        if self.simultaneous_critical_width_bps < 0:
            raise ValueError("statistical split critical width cannot be negative")
        if tuple(item.horizon_minutes for item in self.bands) != DEFAULT_STANCE_HORIZONS_MINUTES:
            raise ValueError("statistical split must report the complete predeclared horizon family")
        if any(item.sample_size != self.event_count for item in self.bands):
            raise ValueError("statistical split horizon bands must share the event denominator")


@dataclass(frozen=True, slots=True)
class StanceStatisticalValidationReport:
    report_id: str
    schema_version: str
    policy_version: str
    research_only: bool
    execution_authority: bool
    implementation_version: str
    source_dataset_id: str
    source_as_of: str
    source_max_baseline_delay_seconds: Decimal
    family_id: str
    policy_currency: str
    instrument: str
    stance_ruleset_version: str
    price_semantics: str
    horizon_minutes: tuple[int, ...]
    primary_horizon_minutes: int
    split_policy: str
    familywise_confidence: Decimal
    bootstrap_iterations: int
    simultaneous_method: str
    minimum_directional_events: int
    minimum_calibration_events: int
    minimum_holdout_events: int
    minimum_observed_event_fraction: Decimal
    events_considered: int
    events_observed: int
    events_excluded: int
    observed_event_fraction: Decimal
    directional_event_count: int
    nondirectional_event_count: int
    calibration_event_count: int
    holdout_event_count: int
    calibration: ChronologicalStatisticalSplit | None
    holdout: ChronologicalStatisticalSplit | None
    disposition: StanceStatisticalDisposition
    reasons: tuple[str, ...]

    def __post_init__(self) -> None:
        if self.schema_version != STANCE_STATISTICAL_SCHEMA_VERSION:
            raise ValueError("unsupported stance statistical validation schema")
        if self.policy_version != STANCE_STATISTICAL_POLICY_VERSION:
            raise ValueError("unsupported stance statistical policy version")
        if self.research_only is not True or self.execution_authority is not False:
            raise ValueError("stance statistical validation must remain research-only")
        if not self.implementation_version.strip() or not self.source_dataset_id.strip() or not self.source_as_of.strip():
            raise ValueError("stance statistical report implementation/dataset/cutoff identity is required")
        if self.source_max_baseline_delay_seconds != FIXED_MAX_BASELINE_DELAY_SECONDS:
            raise ValueError("stance statistical report baseline-delay policy is fixed")
        if self.horizon_minutes != DEFAULT_STANCE_HORIZONS_MINUTES:
            raise ValueError("stance statistical report must use the predeclared horizon family")
        if self.primary_horizon_minutes != PRIMARY_HORIZON_MINUTES:
            raise ValueError("stance statistical report primary horizon is fixed by policy")
        if self.split_policy != SPLIT_POLICY or self.simultaneous_method != SIMULTANEOUS_METHOD:
            raise ValueError("stance statistical report methodology does not match policy")
        if self.familywise_confidence != FAMILYWISE_CONFIDENCE:
            raise ValueError("stance statistical family-wise confidence is fixed by policy")
        if self.bootstrap_iterations != BOOTSTRAP_ITERATIONS:
            raise ValueError("stance statistical bootstrap iterations are fixed by policy")
        if self.minimum_directional_events != MIN_DIRECTIONAL_EVENTS:
            raise ValueError("stance statistical minimum directional events are fixed by policy")
        if self.minimum_calibration_events != MIN_CALIBRATION_EVENTS or self.minimum_holdout_events != MIN_HOLDOUT_EVENTS:
            raise ValueError("stance statistical split minimums are fixed by policy")
        if self.minimum_observed_event_fraction != MIN_OBSERVED_EVENT_FRACTION:
            raise ValueError("stance statistical observed-event fraction is fixed by policy")
        if self.events_considered != self.events_observed + self.events_excluded:
            raise ValueError("stance statistical source event denominator is inconsistent")
        if self.events_observed != self.directional_event_count + self.nondirectional_event_count:
            raise ValueError("stance statistical directional denominator is inconsistent")
        expected_fraction = _observed_fraction(self.events_observed, self.events_considered)
        if self.observed_event_fraction != expected_fraction:
            raise ValueError("stance statistical observed-event fraction does not match counts")
        if self.calibration_event_count + self.holdout_event_count != self.directional_event_count:
            raise ValueError("stance statistical chronological split does not cover all directional events")
        if self.calibration is None or self.holdout is None:
            if self.disposition is not StanceStatisticalDisposition.INSUFFICIENT_EVIDENCE:
                raise ValueError("missing statistical split can only yield insufficient evidence")
        else:
            if self.calibration.event_count != self.calibration_event_count:
                raise ValueError("calibration split count mismatch")
            if self.holdout.event_count != self.holdout_event_count:
                raise ValueError("holdout split count mismatch")
            if set(self.calibration.event_ids) & set(self.holdout.event_ids):
                raise ValueError("calibration and holdout event IDs cannot overlap")
        if not self.reasons:
            raise ValueError("stance statistical report must explain its disposition")
        if self.report_id != _report_id(self):
            raise ValueError("stance statistical report ID does not match its evidence payload")


@dataclass(frozen=True, slots=True)
class _DirectionalPanel:
    event_id: str
    available_at: str
    returns_by_horizon: tuple[Decimal, ...]


def validate_stance_outcome_statistics(dataset: StanceOutcomeDataset) -> StanceStatisticalValidationReport:
    """Validate the fixed central-bank stance outcome family without selecting a best horizon.

    The only inferential candidate state is an informational research candidate at the
    predeclared 60-minute horizon. Every confidence band is simultaneous across the complete
    5/15/60/240-minute family, and every bootstrap iteration jointly resamples event panels.
    """
    _validate_source_dataset(dataset)
    source_as_of = dataset.as_of
    if source_as_of is None:
        raise ValueError("stance statistical validation requires a frozen as_of cutoff")
    directional, nondirectional_count = _directional_panels(dataset.outcomes)
    observed_fraction = _observed_fraction(dataset.events_observed, dataset.events_considered)
    calibration_count, holdout_count = _split_counts(len(directional))
    calibration: ChronologicalStatisticalSplit | None = None
    holdout: ChronologicalStatisticalSplit | None = None
    reasons: list[str] = []

    enough_counts = (
        len(directional) >= MIN_DIRECTIONAL_EVENTS
        and calibration_count >= MIN_CALIBRATION_EVENTS
        and holdout_count >= MIN_HOLDOUT_EVENTS
    )
    coverage_ok = observed_fraction >= MIN_OBSERVED_EVENT_FRACTION
    if not coverage_ok:
        reasons.append(
            f"observed event fraction {observed_fraction} is below required {MIN_OBSERVED_EVENT_FRACTION}"
        )
    if not enough_counts:
        reasons.append(
            "directional sample is below fixed minimums "
            f"total={len(directional)}/{MIN_DIRECTIONAL_EVENTS} "
            f"calibration={calibration_count}/{MIN_CALIBRATION_EVENTS} "
            f"holdout={holdout_count}/{MIN_HOLDOUT_EVENTS}"
        )

    if enough_counts:
        calibration_panels = directional[:calibration_count]
        holdout_panels = directional[calibration_count:]
        calibration = _simultaneous_split("calibration", calibration_panels, BOOTSTRAP_SEED)
        holdout = _simultaneous_split("holdout", holdout_panels, BOOTSTRAP_SEED + 1)

    if not enough_counts or not coverage_ok or holdout is None:
        disposition = StanceStatisticalDisposition.INSUFFICIENT_EVIDENCE
        if not reasons:
            reasons.append("fixed statistical evidence requirements are not satisfied")
    else:
        primary = next(item for item in holdout.bands if item.horizon_minutes == PRIMARY_HORIZON_MINUTES)
        if primary.lower_simultaneous_mean_bps > 0:
            disposition = StanceStatisticalDisposition.INFORMATIONAL_SIGNAL_CANDIDATE
            reasons.append(
                "untouched holdout 60-minute simultaneous lower confidence bound is above zero; "
                "this is informational market-reaction evidence, not executable expectancy"
            )
        elif primary.upper_simultaneous_mean_bps < 0:
            disposition = StanceStatisticalDisposition.REJECTED
            reasons.append(
                "untouched holdout 60-minute simultaneous upper confidence bound is below zero"
            )
        else:
            disposition = StanceStatisticalDisposition.INSUFFICIENT_EVIDENCE
            reasons.append(
                "untouched holdout 60-minute simultaneous confidence interval includes zero"
            )
        negative_secondary = tuple(
            item.horizon_minutes
            for item in holdout.bands
            if item.horizon_minutes != PRIMARY_HORIZON_MINUTES and item.upper_simultaneous_mean_bps < 0
        )
        if negative_secondary:
            reasons.append(
                "secondary horizons with simultaneous evidence below zero: "
                + ",".join(str(item) for item in negative_secondary)
            )

    source_as_of_text = source_as_of.isoformat()
    reasons_tuple = tuple(reasons)
    report_id = _statistical_report_id(
        implementation_version=__version__,
        source_dataset_id=dataset.dataset_id,
        source_as_of=source_as_of_text,
        source_max_baseline_delay_seconds=dataset.max_baseline_delay_seconds,
        family_id=dataset.family_id,
        policy_currency=dataset.policy_currency,
        instrument=dataset.instrument,
        stance_ruleset_version=dataset.ruleset_version,
        price_semantics=dataset.price_semantics,
        horizon_minutes=dataset.horizon_minutes,
        events_considered=dataset.events_considered,
        events_observed=dataset.events_observed,
        events_excluded=dataset.events_excluded,
        observed_event_fraction=observed_fraction,
        directional_event_count=len(directional),
        nondirectional_event_count=nondirectional_count,
        calibration_event_count=calibration_count,
        holdout_event_count=holdout_count,
        calibration=calibration,
        holdout=holdout,
        disposition=disposition,
        reasons=reasons_tuple,
    )
    return StanceStatisticalValidationReport(
        report_id=report_id,
        schema_version=STANCE_STATISTICAL_SCHEMA_VERSION,
        policy_version=STANCE_STATISTICAL_POLICY_VERSION,
        research_only=True,
        execution_authority=False,
        implementation_version=__version__,
        source_dataset_id=dataset.dataset_id,
        source_as_of=source_as_of_text,
        source_max_baseline_delay_seconds=dataset.max_baseline_delay_seconds,
        family_id=dataset.family_id,
        policy_currency=dataset.policy_currency,
        instrument=dataset.instrument,
        stance_ruleset_version=dataset.ruleset_version,
        price_semantics=dataset.price_semantics,
        horizon_minutes=dataset.horizon_minutes,
        primary_horizon_minutes=PRIMARY_HORIZON_MINUTES,
        split_policy=SPLIT_POLICY,
        familywise_confidence=FAMILYWISE_CONFIDENCE,
        bootstrap_iterations=BOOTSTRAP_ITERATIONS,
        simultaneous_method=SIMULTANEOUS_METHOD,
        minimum_directional_events=MIN_DIRECTIONAL_EVENTS,
        minimum_calibration_events=MIN_CALIBRATION_EVENTS,
        minimum_holdout_events=MIN_HOLDOUT_EVENTS,
        minimum_observed_event_fraction=MIN_OBSERVED_EVENT_FRACTION,
        events_considered=dataset.events_considered,
        events_observed=dataset.events_observed,
        events_excluded=dataset.events_excluded,
        observed_event_fraction=observed_fraction,
        directional_event_count=len(directional),
        nondirectional_event_count=nondirectional_count,
        calibration_event_count=calibration_count,
        holdout_event_count=holdout_count,
        calibration=calibration,
        holdout=holdout,
        disposition=disposition,
        reasons=reasons_tuple,
    )


def _validate_source_dataset(dataset: StanceOutcomeDataset) -> None:
    if dataset.research_only is not True or dataset.execution_authority is not False:
        raise ValueError("stance statistical validation requires a research-only source dataset")
    if dataset.horizon_minutes != DEFAULT_STANCE_HORIZONS_MINUTES:
        raise ValueError(
            "stance statistical validation requires the fixed 5/15/60/240-minute horizon family"
        )
    if dataset.price_semantics != STANCE_OUTCOME_PRICE_SEMANTICS:
        raise ValueError("stance statistical validation requires midpoint informational price semantics")
    if dataset.as_of is None:
        raise ValueError("stance statistical validation requires a frozen as_of cutoff")
    if dataset.max_baseline_delay_seconds != FIXED_MAX_BASELINE_DELAY_SECONDS:
        raise ValueError(
            "stance statistical validation requires the fixed 300-second baseline-delay policy"
        )
    if dataset.events_considered < 1:
        raise ValueError("stance statistical validation requires at least one considered event")


def _directional_panels(
    outcomes: Iterable[StanceOutcomeObservation],
) -> tuple[tuple[_DirectionalPanel, ...], int]:
    grouped: dict[str, list[StanceOutcomeObservation]] = {}
    for item in outcomes:
        grouped.setdefault(item.current_version_id, []).append(item)
    directional: list[_DirectionalPanel] = []
    nondirectional_count = 0
    for event_id, values in grouped.items():
        ordered = tuple(sorted(values, key=lambda item: item.horizon_minutes))
        if tuple(item.horizon_minutes for item in ordered) != DEFAULT_STANCE_HORIZONS_MINUTES:
            raise ValueError("stance statistical input event is missing a predeclared horizon")
        available_times = {item.document_available_at for item in ordered}
        directions = {item.stance_direction for item in ordered}
        dispositions = {item.stance_disposition for item in ordered}
        aligned = tuple(item.stance_aligned_return_bps for item in ordered)
        if len(available_times) != 1 or len(directions) != 1 or len(dispositions) != 1:
            raise ValueError("stance statistical input event metadata is inconsistent across horizons")
        if any(value is None for value in aligned):
            if not all(value is None for value in aligned):
                raise ValueError("stance statistical input cannot mix directional and nondirectional horizons")
            nondirectional_count += 1
            continue
        directional.append(
            _DirectionalPanel(
                event_id=event_id,
                available_at=next(iter(available_times)).isoformat(),
                returns_by_horizon=tuple(value for value in aligned if value is not None),
            )
        )
    directional.sort(key=lambda item: (item.available_at, item.event_id))
    return tuple(directional), nondirectional_count


def _split_counts(sample_size: int) -> tuple[int, int]:
    if sample_size < 0:
        raise ValueError("stance statistical sample size cannot be negative")
    calibration = (sample_size * CALIBRATION_NUMERATOR) // CALIBRATION_DENOMINATOR
    return calibration, sample_size - calibration


def _simultaneous_split(
    name: str,
    panels: tuple[_DirectionalPanel, ...],
    seed: int,
) -> ChronologicalStatisticalSplit:
    if not panels:
        raise ValueError("simultaneous stance split requires events")
    sample_size = len(panels)
    horizon_count = len(DEFAULT_STANCE_HORIZONS_MINUTES)
    observed_means = tuple(
        sum((panel.returns_by_horizon[index] for panel in panels), Decimal("0")) / Decimal(sample_size)
        for index in range(horizon_count)
    )
    random = Random(seed)
    maximum_deviations: list[Decimal] = []
    for _ in range(BOOTSTRAP_ITERATIONS):
        indices = tuple(random.randrange(sample_size) for _ in range(sample_size))
        iteration_max = Decimal("0")
        for horizon_index in range(horizon_count):
            bootstrap_mean = (
                sum(
                    (panels[event_index].returns_by_horizon[horizon_index] for event_index in indices),
                    Decimal("0"),
                )
                / Decimal(sample_size)
            )
            iteration_max = max(iteration_max, abs(bootstrap_mean - observed_means[horizon_index]))
        maximum_deviations.append(iteration_max)
    critical_width = _quantile(tuple(sorted(maximum_deviations)), FAMILYWISE_CONFIDENCE)
    bands = tuple(
        HorizonStatisticalBand(
            horizon_minutes=horizon,
            sample_size=sample_size,
            mean_stance_aligned_return_bps=observed_means[index],
            lower_simultaneous_mean_bps=observed_means[index] - critical_width,
            upper_simultaneous_mean_bps=observed_means[index] + critical_width,
            stance_aligned_hit_rate=(
                Decimal(sum(panel.returns_by_horizon[index] > 0 for panel in panels))
                / Decimal(sample_size)
            ),
        )
        for index, horizon in enumerate(DEFAULT_STANCE_HORIZONS_MINUTES)
    )
    return ChronologicalStatisticalSplit(
        name=name,
        event_count=sample_size,
        first_document_available_at=panels[0].available_at,
        last_document_available_at=panels[-1].available_at,
        event_ids=tuple(panel.event_id for panel in panels),
        bootstrap_seed=seed,
        simultaneous_critical_width_bps=critical_width,
        bands=bands,
    )


def _observed_fraction(observed: int, considered: int) -> Decimal:
    if considered < 1 or observed < 0 or observed > considered:
        raise ValueError("stance statistical observed/considered counts are invalid")
    return Decimal(observed) / Decimal(considered)


def _quantile(values: tuple[Decimal, ...], probability: Decimal) -> Decimal:
    if not values:
        raise ValueError("cannot compute stance statistical quantile from an empty sequence")
    if not Decimal("0") < probability < Decimal("1"):
        raise ValueError("stance statistical quantile probability must be in (0,1)")
    position = probability * Decimal(len(values) - 1)
    lower_index = int(position)
    upper_index = min(lower_index + 1, len(values) - 1)
    fraction = position - Decimal(lower_index)
    return values[lower_index] + (values[upper_index] - values[lower_index]) * fraction


def _report_id(report: StanceStatisticalValidationReport) -> str:
    return _statistical_report_id(
        implementation_version=report.implementation_version,
        source_dataset_id=report.source_dataset_id,
        source_as_of=report.source_as_of,
        source_max_baseline_delay_seconds=report.source_max_baseline_delay_seconds,
        family_id=report.family_id,
        policy_currency=report.policy_currency,
        instrument=report.instrument,
        stance_ruleset_version=report.stance_ruleset_version,
        price_semantics=report.price_semantics,
        horizon_minutes=report.horizon_minutes,
        events_considered=report.events_considered,
        events_observed=report.events_observed,
        events_excluded=report.events_excluded,
        observed_event_fraction=report.observed_event_fraction,
        directional_event_count=report.directional_event_count,
        nondirectional_event_count=report.nondirectional_event_count,
        calibration_event_count=report.calibration_event_count,
        holdout_event_count=report.holdout_event_count,
        calibration=report.calibration,
        holdout=report.holdout,
        disposition=report.disposition,
        reasons=report.reasons,
    )


def _statistical_report_id(
    *,
    implementation_version: str,
    source_dataset_id: str,
    source_as_of: str,
    source_max_baseline_delay_seconds: Decimal,
    family_id: str,
    policy_currency: str,
    instrument: str,
    stance_ruleset_version: str,
    price_semantics: str,
    horizon_minutes: tuple[int, ...],
    events_considered: int,
    events_observed: int,
    events_excluded: int,
    observed_event_fraction: Decimal,
    directional_event_count: int,
    nondirectional_event_count: int,
    calibration_event_count: int,
    holdout_event_count: int,
    calibration: ChronologicalStatisticalSplit | None,
    holdout: ChronologicalStatisticalSplit | None,
    disposition: StanceStatisticalDisposition,
    reasons: tuple[str, ...],
) -> str:
    payload = {
        "schema_version": STANCE_STATISTICAL_SCHEMA_VERSION,
        "policy_version": STANCE_STATISTICAL_POLICY_VERSION,
        "research_only": True,
        "execution_authority": False,
        "implementation_version": implementation_version,
        "source_dataset_id": source_dataset_id,
        "source_as_of": source_as_of,
        "source_max_baseline_delay_seconds": str(source_max_baseline_delay_seconds),
        "family_id": family_id,
        "policy_currency": policy_currency,
        "instrument": instrument,
        "stance_ruleset_version": stance_ruleset_version,
        "price_semantics": price_semantics,
        "horizon_minutes": list(horizon_minutes),
        "primary_horizon_minutes": PRIMARY_HORIZON_MINUTES,
        "split_policy": SPLIT_POLICY,
        "familywise_confidence": str(FAMILYWISE_CONFIDENCE),
        "bootstrap_iterations": BOOTSTRAP_ITERATIONS,
        "simultaneous_method": SIMULTANEOUS_METHOD,
        "minimum_directional_events": MIN_DIRECTIONAL_EVENTS,
        "minimum_calibration_events": MIN_CALIBRATION_EVENTS,
        "minimum_holdout_events": MIN_HOLDOUT_EVENTS,
        "minimum_observed_event_fraction": str(MIN_OBSERVED_EVENT_FRACTION),
        "events_considered": events_considered,
        "events_observed": events_observed,
        "events_excluded": events_excluded,
        "observed_event_fraction": str(observed_event_fraction),
        "directional_event_count": directional_event_count,
        "nondirectional_event_count": nondirectional_event_count,
        "calibration_event_count": calibration_event_count,
        "holdout_event_count": holdout_event_count,
        "calibration": _split_payload(calibration),
        "holdout": _split_payload(holdout),
        "disposition": disposition.value,
        "reasons": list(reasons),
    }
    return hashlib.sha256(_canonical_json(payload)).hexdigest()


def _split_payload(split: ChronologicalStatisticalSplit | None) -> object:
    if split is None:
        return None
    return {
        "name": split.name,
        "event_count": split.event_count,
        "first_document_available_at": split.first_document_available_at,
        "last_document_available_at": split.last_document_available_at,
        "event_ids": list(split.event_ids),
        "bootstrap_seed": split.bootstrap_seed,
        "simultaneous_critical_width_bps": str(split.simultaneous_critical_width_bps),
        "bands": [
            {
                "horizon_minutes": band.horizon_minutes,
                "sample_size": band.sample_size,
                "mean_stance_aligned_return_bps": str(band.mean_stance_aligned_return_bps),
                "lower_simultaneous_mean_bps": str(band.lower_simultaneous_mean_bps),
                "upper_simultaneous_mean_bps": str(band.upper_simultaneous_mean_bps),
                "stance_aligned_hit_rate": str(band.stance_aligned_hit_rate),
            }
            for band in split.bands
        ],
    }


def _canonical_json(value: object) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
