from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Iterable

from forex_trader.domain.models import Candle
from forex_trader.intelligence.official_documents import OfficialDocumentVersion, compare_document_versions
from forex_trader.research.central_bank_stance import (
    CentralBankStanceEvidence,
    EvidenceDisposition,
    StanceDirection,
    extract_central_bank_stance,
)


STANCE_OUTCOME_SCHEMA_VERSION = "central-bank-stance-outcome-v1"
STANCE_OUTCOME_PRICE_SEMANTICS = "completed_midpoint_candle_open_proxy_not_execution"
DEFAULT_STANCE_HORIZONS_MINUTES: tuple[int, ...] = (5, 15, 60, 240)


@dataclass(frozen=True, slots=True)
class StanceOutcomeObservation:
    outcome_id: str
    schema_version: str
    research_only: bool
    execution_authority: bool
    ruleset_version: str
    family_id: str
    previous_version_id: str
    current_version_id: str
    policy_currency: str
    instrument: str
    document_available_at: datetime
    stance_direction: StanceDirection
    stance_disposition: EvidenceDisposition
    evidence_quality: Decimal
    evidence_quality_is_probability: bool
    horizon_minutes: int
    baseline_time: datetime
    baseline_price: Decimal
    baseline_delay_seconds: Decimal
    observation_time: datetime
    observation_price: Decimal
    raw_return_bps: Decimal
    stance_aligned_return_bps: Decimal | None
    price_semantics: str = STANCE_OUTCOME_PRICE_SEMANTICS

    def __post_init__(self) -> None:
        if self.schema_version != STANCE_OUTCOME_SCHEMA_VERSION:
            raise ValueError("unsupported stance outcome schema version")
        if self.research_only is not True or self.execution_authority is not False:
            raise ValueError("stance outcomes must remain research-only with no execution authority")
        if self.evidence_quality_is_probability:
            raise ValueError("stance outcome evidence quality cannot be labeled probability")
        if not Decimal("0") <= self.evidence_quality <= Decimal("1"):
            raise ValueError("stance outcome evidence_quality must be in [0,1]")
        if self.horizon_minutes < 1:
            raise ValueError("stance outcome horizon must be positive")
        if self.document_available_at.tzinfo is None or self.baseline_time.tzinfo is None or self.observation_time.tzinfo is None:
            raise ValueError("stance outcome timestamps must be timezone-aware")
        if self.baseline_time < self.document_available_at:
            raise ValueError("stance outcome baseline cannot precede document availability")
        if self.observation_time < self.baseline_time + timedelta(minutes=self.horizon_minutes):
            raise ValueError("stance outcome observation cannot precede its requested horizon")
        if self.baseline_price <= 0 or self.observation_price <= 0:
            raise ValueError("stance outcome prices must be positive")
        if self.baseline_delay_seconds < 0:
            raise ValueError("stance outcome baseline delay cannot be negative")
        expected_delay = _seconds_decimal(self.baseline_time - self.document_available_at)
        if self.baseline_delay_seconds != expected_delay:
            raise ValueError("stance outcome baseline delay does not match timestamps")
        if self.price_semantics != STANCE_OUTCOME_PRICE_SEMANTICS:
            raise ValueError("unsupported stance outcome price semantics")
        _instrument_currencies(self.instrument)
        if self.policy_currency not in _instrument_currencies(self.instrument):
            raise ValueError("policy currency must be a leg of the analyzed instrument")
        expected_raw = _return_bps(self.baseline_price, self.observation_price)
        if self.raw_return_bps != expected_raw:
            raise ValueError("stance outcome raw return does not match prices")
        expected_aligned = _align_return(self.raw_return_bps, self.stance_direction, self.policy_currency, self.instrument)
        if self.stance_aligned_return_bps != expected_aligned:
            raise ValueError("stance-aligned return does not match stance/instrument polarity")
        expected_id = _outcome_id(
            family_id=self.family_id,
            current_version_id=self.current_version_id,
            ruleset_version=self.ruleset_version,
            instrument=self.instrument,
            horizon_minutes=self.horizon_minutes,
            baseline_time=self.baseline_time,
            baseline_price=self.baseline_price,
            observation_time=self.observation_time,
            observation_price=self.observation_price,
        )
        if self.outcome_id != expected_id:
            raise ValueError("stance outcome ID does not match its evidence payload")


@dataclass(frozen=True, slots=True)
class StanceOutcomeExclusion:
    current_version_id: str
    document_available_at: datetime
    stance_direction: StanceDirection
    stance_disposition: EvidenceDisposition
    evidence_quality: Decimal
    reason: str

    def __post_init__(self) -> None:
        if not self.current_version_id.strip() or not self.reason.strip():
            raise ValueError("stance outcome exclusion identity and reason are required")
        if self.document_available_at.tzinfo is None:
            raise ValueError("stance outcome exclusion timestamp must be timezone-aware")
        if not Decimal("0") <= self.evidence_quality <= Decimal("1"):
            raise ValueError("stance outcome exclusion evidence quality must be in [0,1]")


@dataclass(frozen=True, slots=True)
class StanceOutcomeSummary:
    stance_direction: StanceDirection
    stance_disposition: EvidenceDisposition
    horizon_minutes: int
    sample_size: int
    directional_sample_size: int
    mean_evidence_quality: Decimal
    mean_raw_return_bps: Decimal
    median_raw_return_bps: Decimal
    mean_stance_aligned_return_bps: Decimal | None
    median_stance_aligned_return_bps: Decimal | None
    stance_aligned_hit_rate: Decimal | None

    def __post_init__(self) -> None:
        if self.horizon_minutes < 1 or self.sample_size < 1:
            raise ValueError("stance outcome summary requires a positive horizon and sample")
        if not 0 <= self.directional_sample_size <= self.sample_size:
            raise ValueError("stance outcome directional sample is invalid")
        if not Decimal("0") <= self.mean_evidence_quality <= Decimal("1"):
            raise ValueError("mean evidence quality must be in [0,1]")
        aligned_values = (
            self.mean_stance_aligned_return_bps,
            self.median_stance_aligned_return_bps,
            self.stance_aligned_hit_rate,
        )
        if self.directional_sample_size == 0 and any(value is not None for value in aligned_values):
            raise ValueError("non-directional stance summary cannot report aligned return statistics")
        if self.directional_sample_size > 0 and any(value is None for value in aligned_values):
            raise ValueError("directional stance summary requires aligned return statistics")
        if self.stance_aligned_hit_rate is not None and not Decimal("0") <= self.stance_aligned_hit_rate <= Decimal("1"):
            raise ValueError("stance-aligned hit rate must be in [0,1]")


@dataclass(frozen=True, slots=True)
class StanceOutcomeDataset:
    dataset_id: str
    schema_version: str
    research_only: bool
    execution_authority: bool
    family_id: str
    policy_currency: str
    instrument: str
    ruleset_version: str
    horizon_minutes: tuple[int, ...]
    max_baseline_delay_seconds: Decimal
    as_of: datetime | None
    price_semantics: str
    events_considered: int
    events_observed: int
    events_excluded: int
    outcomes: tuple[StanceOutcomeObservation, ...]
    exclusions: tuple[StanceOutcomeExclusion, ...]
    summaries: tuple[StanceOutcomeSummary, ...]

    def __post_init__(self) -> None:
        if self.schema_version != STANCE_OUTCOME_SCHEMA_VERSION:
            raise ValueError("unsupported stance outcome dataset schema")
        if self.research_only is not True or self.execution_authority is not False:
            raise ValueError("stance outcome dataset must remain research-only")
        if not self.family_id.strip() or not self.ruleset_version.strip():
            raise ValueError("stance outcome dataset family/ruleset identity is required")
        base, quote = _instrument_currencies(self.instrument)
        if self.policy_currency not in {base, quote}:
            raise ValueError("policy currency must be a leg of the analyzed instrument")
        if not self.horizon_minutes or tuple(sorted(set(self.horizon_minutes))) != self.horizon_minutes:
            raise ValueError("stance outcome horizons must be sorted, unique and non-empty")
        if min(self.horizon_minutes) < 1:
            raise ValueError("stance outcome horizons must be positive")
        if self.max_baseline_delay_seconds < 0:
            raise ValueError("max baseline delay cannot be negative")
        if self.as_of is not None and self.as_of.tzinfo is None:
            raise ValueError("stance outcome as_of must be timezone-aware")
        if self.price_semantics != STANCE_OUTCOME_PRICE_SEMANTICS:
            raise ValueError("unsupported stance outcome dataset price semantics")
        if self.events_considered != self.events_observed + self.events_excluded:
            raise ValueError("stance outcome event denominator is inconsistent")
        if self.events_excluded != len(self.exclusions):
            raise ValueError("stance outcome exclusion count is inconsistent")
        observed_ids = {item.current_version_id for item in self.outcomes}
        if self.events_observed != len(observed_ids):
            raise ValueError("stance outcome observed event count is inconsistent")
        for version_id in observed_ids:
            horizons = tuple(sorted(item.horizon_minutes for item in self.outcomes if item.current_version_id == version_id))
            if horizons != self.horizon_minutes:
                raise ValueError("every observed stance event must contain the complete requested horizon panel")
        expected_id = _dataset_id(
            family_id=self.family_id,
            policy_currency=self.policy_currency,
            instrument=self.instrument,
            ruleset_version=self.ruleset_version,
            horizon_minutes=self.horizon_minutes,
            max_baseline_delay_seconds=self.max_baseline_delay_seconds,
            as_of=self.as_of,
            outcomes=self.outcomes,
            exclusions=self.exclusions,
        )
        if self.dataset_id != expected_id:
            raise ValueError("stance outcome dataset ID does not match its point-in-time evidence")


def build_stance_outcome_dataset(
    versions: Iterable[OfficialDocumentVersion],
    candles: Iterable[Candle],
    *,
    instrument: str,
    horizon_minutes: Iterable[int] = DEFAULT_STANCE_HORIZONS_MINUTES,
    max_baseline_delay_seconds: Decimal = Decimal("300"),
    as_of: datetime | None = None,
) -> StanceOutcomeDataset:
    ordered_versions = tuple(sorted(versions, key=lambda item: (item.available_at, item.version_id)))
    if len(ordered_versions) < 2:
        raise ValueError("stance outcome research requires at least two document versions")
    family_ids = {item.family_id for item in ordered_versions}
    currencies = {item.currency.upper() for item in ordered_versions}
    institutions = {item.institution for item in ordered_versions}
    document_types = {item.document_type for item in ordered_versions}
    if len(family_ids) != 1 or len(currencies) != 1 or len(institutions) != 1 or len(document_types) != 1:
        raise ValueError("stance outcome lineage must preserve family, currency, institution and document type")
    family_id = next(iter(family_ids))
    policy_currency = next(iter(currencies))
    normalized_instrument = instrument.strip().upper()
    if policy_currency not in _instrument_currencies(normalized_instrument):
        raise ValueError("policy currency must be a leg of the analyzed instrument")
    horizons = _normalize_horizons(horizon_minutes)
    if max_baseline_delay_seconds < 0:
        raise ValueError("max_baseline_delay_seconds cannot be negative")
    if as_of is not None and as_of.tzinfo is None:
        raise ValueError("as_of must be timezone-aware")

    complete_candles = tuple(sorted((item for item in candles if item.complete), key=lambda item: item.time))
    if not complete_candles:
        raise ValueError("stance outcome research requires completed candle observations")
    if len({item.time for item in complete_candles}) != len(complete_candles):
        raise ValueError("stance outcome candles cannot contain duplicate timestamps")

    version_by_id = {item.version_id: item for item in ordered_versions}
    if len(version_by_id) != len(ordered_versions):
        raise ValueError("stance outcome document versions cannot contain duplicate version IDs")

    outcomes: list[StanceOutcomeObservation] = []
    exclusions: list[StanceOutcomeExclusion] = []
    events_considered = 0
    ruleset_version: str | None = None

    for current in ordered_versions:
        if current.predecessor_version_id is None:
            continue
        if as_of is not None and current.available_at > as_of:
            continue
        events_considered += 1
        previous = version_by_id.get(current.predecessor_version_id)
        if previous is None:
            raise ValueError("stance outcome lineage predecessor is missing")
        if previous.available_at >= current.available_at:
            raise ValueError("stance outcome lineage is not strictly point-in-time ordered")
        if previous.currency.upper() != policy_currency or previous.institution != current.institution or previous.document_type != current.document_type:
            raise ValueError("stance outcome predecessor changes the configured policy lineage")

        evidence = extract_central_bank_stance(compare_document_versions(previous, current))
        if ruleset_version is None:
            ruleset_version = evidence.ruleset_version
        elif ruleset_version != evidence.ruleset_version:
            raise ValueError("stance outcome dataset cannot mix stance ruleset versions")

        available_candles = tuple(
            item for item in complete_candles if as_of is None or item.time <= as_of
        )
        baseline = next((item for item in available_candles if item.time >= current.available_at), None)
        if baseline is None:
            exclusions.append(_exclusion(current, evidence, "baseline_missing"))
            continue
        baseline_delay = _seconds_decimal(baseline.time - current.available_at)
        if baseline_delay > max_baseline_delay_seconds:
            exclusions.append(
                _exclusion(
                    current,
                    evidence,
                    f"baseline_delay_exceeded:{baseline_delay}>{max_baseline_delay_seconds}",
                )
            )
            continue

        observations: list[tuple[int, Candle]] = []
        missing_horizon: int | None = None
        for horizon in horizons:
            target = baseline.time + timedelta(minutes=horizon)
            observation = next((item for item in available_candles if item.time >= target), None)
            if observation is None:
                missing_horizon = horizon
                break
            observations.append((horizon, observation))
        if missing_horizon is not None:
            exclusions.append(_exclusion(current, evidence, f"missing_horizon:{missing_horizon}"))
            continue

        for horizon, observation in observations:
            outcomes.append(
                _observation(
                    current=current,
                    evidence=evidence,
                    policy_currency=policy_currency,
                    instrument=normalized_instrument,
                    horizon_minutes=horizon,
                    baseline=baseline,
                    observation=observation,
                )
            )

    if ruleset_version is None:
        raise ValueError("stance outcome research has no comparable document events in the requested point-in-time window")
    ordered_outcomes = tuple(
        sorted(outcomes, key=lambda item: (item.document_available_at, item.current_version_id, item.horizon_minutes))
    )
    ordered_exclusions = tuple(sorted(exclusions, key=lambda item: (item.document_available_at, item.current_version_id)))
    summaries = summarize_stance_outcomes(ordered_outcomes)
    events_observed = len({item.current_version_id for item in ordered_outcomes})
    dataset_id = _dataset_id(
        family_id=family_id,
        policy_currency=policy_currency,
        instrument=normalized_instrument,
        ruleset_version=ruleset_version,
        horizon_minutes=horizons,
        max_baseline_delay_seconds=max_baseline_delay_seconds,
        as_of=as_of,
        outcomes=ordered_outcomes,
        exclusions=ordered_exclusions,
    )
    return StanceOutcomeDataset(
        dataset_id=dataset_id,
        schema_version=STANCE_OUTCOME_SCHEMA_VERSION,
        research_only=True,
        execution_authority=False,
        family_id=family_id,
        policy_currency=policy_currency,
        instrument=normalized_instrument,
        ruleset_version=ruleset_version,
        horizon_minutes=horizons,
        max_baseline_delay_seconds=max_baseline_delay_seconds,
        as_of=as_of,
        price_semantics=STANCE_OUTCOME_PRICE_SEMANTICS,
        events_considered=events_considered,
        events_observed=events_observed,
        events_excluded=len(ordered_exclusions),
        outcomes=ordered_outcomes,
        exclusions=ordered_exclusions,
        summaries=summaries,
    )


def summarize_stance_outcomes(outcomes: Iterable[StanceOutcomeObservation]) -> tuple[StanceOutcomeSummary, ...]:
    buckets: dict[tuple[StanceDirection, EvidenceDisposition, int], list[StanceOutcomeObservation]] = {}
    for item in outcomes:
        key = (item.stance_direction, item.stance_disposition, item.horizon_minutes)
        buckets.setdefault(key, []).append(item)
    summaries: list[StanceOutcomeSummary] = []
    for (direction, disposition, horizon), values in sorted(
        buckets.items(), key=lambda item: (item[0][2], item[0][0].value, item[0][1].value)
    ):
        raw = tuple(item.raw_return_bps for item in values)
        aligned = tuple(item.stance_aligned_return_bps for item in values if item.stance_aligned_return_bps is not None)
        quality = tuple(item.evidence_quality for item in values)
        aligned_mean = _mean(aligned) if aligned else None
        aligned_median = _median(aligned) if aligned else None
        hit_rate = (
            Decimal(sum(value > 0 for value in aligned)) / Decimal(len(aligned))
            if aligned
            else None
        )
        summaries.append(
            StanceOutcomeSummary(
                stance_direction=direction,
                stance_disposition=disposition,
                horizon_minutes=horizon,
                sample_size=len(values),
                directional_sample_size=len(aligned),
                mean_evidence_quality=_mean(quality),
                mean_raw_return_bps=_mean(raw),
                median_raw_return_bps=_median(raw),
                mean_stance_aligned_return_bps=aligned_mean,
                median_stance_aligned_return_bps=aligned_median,
                stance_aligned_hit_rate=hit_rate,
            )
        )
    return tuple(summaries)


def _observation(
    *,
    current: OfficialDocumentVersion,
    evidence: CentralBankStanceEvidence,
    policy_currency: str,
    instrument: str,
    horizon_minutes: int,
    baseline: Candle,
    observation: Candle,
) -> StanceOutcomeObservation:
    raw_return = _return_bps(baseline.open, observation.open)
    aligned_return = _align_return(raw_return, evidence.direction, policy_currency, instrument)
    return StanceOutcomeObservation(
        outcome_id=_outcome_id(
            family_id=current.family_id,
            current_version_id=current.version_id,
            ruleset_version=evidence.ruleset_version,
            instrument=instrument,
            horizon_minutes=horizon_minutes,
            baseline_time=baseline.time,
            baseline_price=baseline.open,
            observation_time=observation.time,
            observation_price=observation.open,
        ),
        schema_version=STANCE_OUTCOME_SCHEMA_VERSION,
        research_only=True,
        execution_authority=False,
        ruleset_version=evidence.ruleset_version,
        family_id=current.family_id,
        previous_version_id=evidence.previous_version_id,
        current_version_id=current.version_id,
        policy_currency=policy_currency,
        instrument=instrument,
        document_available_at=current.available_at,
        stance_direction=evidence.direction,
        stance_disposition=evidence.disposition,
        evidence_quality=evidence.evidence_quality,
        evidence_quality_is_probability=False,
        horizon_minutes=horizon_minutes,
        baseline_time=baseline.time,
        baseline_price=baseline.open,
        baseline_delay_seconds=_seconds_decimal(baseline.time - current.available_at),
        observation_time=observation.time,
        observation_price=observation.open,
        raw_return_bps=raw_return,
        stance_aligned_return_bps=aligned_return,
    )


def _exclusion(
    current: OfficialDocumentVersion,
    evidence: CentralBankStanceEvidence,
    reason: str,
) -> StanceOutcomeExclusion:
    return StanceOutcomeExclusion(
        current_version_id=current.version_id,
        document_available_at=current.available_at,
        stance_direction=evidence.direction,
        stance_disposition=evidence.disposition,
        evidence_quality=evidence.evidence_quality,
        reason=reason,
    )


def _normalize_horizons(values: Iterable[int]) -> tuple[int, ...]:
    try:
        horizons = tuple(sorted(set(int(value) for value in values)))
    except (TypeError, ValueError) as exc:
        raise ValueError("stance outcome horizons must be integers") from exc
    if not horizons or min(horizons) < 1:
        raise ValueError("stance outcome horizons must be positive and non-empty")
    return horizons


def _instrument_currencies(instrument: str) -> tuple[str, str]:
    normalized = instrument.strip().upper()
    parts = normalized.split("_")
    if len(parts) != 2 or any(len(part) != 3 or not part.isalpha() for part in parts):
        raise ValueError("instrument must use BASE_QUOTE ISO currency form")
    return parts[0], parts[1]


def _return_bps(start: Decimal, end: Decimal) -> Decimal:
    if start <= 0 or end <= 0:
        raise ValueError("return prices must be positive")
    return ((end / start) - Decimal("1")) * Decimal("10000")


def _align_return(
    raw_return_bps: Decimal,
    direction: StanceDirection,
    policy_currency: str,
    instrument: str,
) -> Decimal | None:
    if direction not in {StanceDirection.HAWKISH, StanceDirection.DOVISH}:
        return None
    base, quote = _instrument_currencies(instrument)
    currency = policy_currency.upper()
    if currency not in {base, quote}:
        raise ValueError("policy currency must be a leg of the analyzed instrument")
    stance_sign = Decimal("1") if direction is StanceDirection.HAWKISH else Decimal("-1")
    leg_sign = Decimal("1") if currency == base else Decimal("-1")
    return raw_return_bps * stance_sign * leg_sign


def _mean(values: tuple[Decimal, ...]) -> Decimal:
    if not values:
        raise ValueError("mean requires observations")
    return sum(values, Decimal("0")) / Decimal(len(values))


def _median(values: tuple[Decimal, ...]) -> Decimal:
    if not values:
        raise ValueError("median requires observations")
    ordered = tuple(sorted(values))
    midpoint = len(ordered) // 2
    if len(ordered) % 2:
        return ordered[midpoint]
    return (ordered[midpoint - 1] + ordered[midpoint]) / Decimal("2")


def _seconds_decimal(delta: timedelta) -> Decimal:
    return Decimal(str(delta.total_seconds()))


def _outcome_id(
    *,
    family_id: str,
    current_version_id: str,
    ruleset_version: str,
    instrument: str,
    horizon_minutes: int,
    baseline_time: datetime,
    baseline_price: Decimal,
    observation_time: datetime,
    observation_price: Decimal,
) -> str:
    payload = {
        "family_id": family_id,
        "current_version_id": current_version_id,
        "ruleset_version": ruleset_version,
        "instrument": instrument,
        "horizon_minutes": horizon_minutes,
        "baseline_time": baseline_time.isoformat(),
        "baseline_price": str(baseline_price),
        "observation_time": observation_time.isoformat(),
        "observation_price": str(observation_price),
    }
    return hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def _dataset_id(
    *,
    family_id: str,
    policy_currency: str,
    instrument: str,
    ruleset_version: str,
    horizon_minutes: tuple[int, ...],
    max_baseline_delay_seconds: Decimal,
    as_of: datetime | None,
    outcomes: tuple[StanceOutcomeObservation, ...],
    exclusions: tuple[StanceOutcomeExclusion, ...],
) -> str:
    payload = {
        "schema_version": STANCE_OUTCOME_SCHEMA_VERSION,
        "family_id": family_id,
        "policy_currency": policy_currency,
        "instrument": instrument,
        "ruleset_version": ruleset_version,
        "horizon_minutes": list(horizon_minutes),
        "max_baseline_delay_seconds": str(max_baseline_delay_seconds),
        "as_of": as_of.isoformat() if as_of is not None else None,
        "outcome_ids": [item.outcome_id for item in outcomes],
        "exclusions": [
            {
                "current_version_id": item.current_version_id,
                "document_available_at": item.document_available_at.isoformat(),
                "stance_direction": item.stance_direction.value,
                "stance_disposition": item.stance_disposition.value,
                "evidence_quality": str(item.evidence_quality),
                "reason": item.reason,
            }
            for item in exclusions
        ],
    }
    return hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
