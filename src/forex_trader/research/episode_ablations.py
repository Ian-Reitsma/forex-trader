from __future__ import annotations

import hashlib
from dataclasses import asdict, dataclass
from decimal import Decimal
from statistics import median
from typing import Iterable

from forex_trader.research.ablations import (
    REQUIRED_ABLATION_VARIANTS,
    AblationVariant,
    MaturedAblationOutcome,
    ProspectiveAblationDecision,
)
from forex_trader.research.evidence import DecisionEvidence, first_observation_per_setup_episode


@dataclass(frozen=True, slots=True)
class VariantEpisodeMetrics:
    variant: AblationVariant
    episode_count: int
    tradeable_episode_count: int
    wins: int
    losses: int
    flat: int
    timeouts: int
    total_r: Decimal
    expectancy_r: Decimal
    median_r: Decimal
    max_drawdown_r: Decimal
    total_estimated_cost_r: Decimal
    average_estimated_cost_r: Decimal


@dataclass(frozen=True, slots=True)
class EpisodeAblationReport:
    raw_snapshot_count: int
    complete_snapshot_count: int
    matched_snapshot_count: int
    structural_snapshot_count: int
    unique_setup_episode_count: int
    selected_matured_episode_count: int
    duplicate_snapshot_count: int
    unmatched_snapshot_count: int
    variants: tuple[VariantEpisodeMetrics, ...]


def ablation_snapshot_id(record: DecisionEvidence) -> str | None:
    """Reconstruct the production snapshot ID without changing historical provenance."""
    if record.signal_time is None:
        return None
    raw = (
        f"{record.campaign_id}|{record.cycle}|{record.instrument.upper()}|"
        f"{record.signal_time.isoformat()}"
    ).encode()
    return "ab-" + hashlib.sha256(raw).hexdigest()[:32]


def build_episode_ablation_report(
    decisions: Iterable[DecisionEvidence],
    prospective: Iterable[ProspectiveAblationDecision],
    outcomes: Iterable[MaturedAblationOutcome],
) -> EpisodeAblationReport:
    """Aggregate paired ablations on first-observation structural setup episodes.

    The first observation is chosen from production decision evidence before checking whether
    that snapshot has a matured outcome. If the preregistered first observation is incomplete
    or not yet matured, the episode is excluded rather than substituting a later snapshot.
    """
    decision_rows = tuple(decisions)
    prospective_rows = tuple(prospective)
    outcome_rows = tuple(outcomes)
    if not decision_rows:
        raise ValueError("episode ablation analysis requires production decision evidence")
    if not prospective_rows:
        raise ValueError("episode ablation analysis requires prospective ablation evidence")
    if not outcome_rows:
        raise ValueError("episode ablation analysis requires matured ablation outcomes")

    expected = set(REQUIRED_ABLATION_VARIANTS)
    prospective_by_snapshot = _group_prospective(prospective_rows)
    outcome_by_snapshot = _group_outcomes(outcome_rows)
    complete_ids = {
        snapshot_id
        for snapshot_id, rows in prospective_by_snapshot.items()
        if set(rows) == expected
        and snapshot_id in outcome_by_snapshot
        and set(outcome_by_snapshot[snapshot_id]) == expected
    }

    decision_by_snapshot: dict[str, DecisionEvidence] = {}
    structural_records: list[DecisionEvidence] = []
    for record in decision_rows:
        snapshot_id = ablation_snapshot_id(record)
        if snapshot_id is None:
            continue
        prior = decision_by_snapshot.setdefault(snapshot_id, record)
        if prior is not record:
            raise ValueError(f"duplicate production decision identity for snapshot {snapshot_id}")
        if _has_structural_anchor(record):
            structural_records.append(record)

    first_records = first_observation_per_setup_episode(structural_records)
    selected_records = tuple(
        record
        for record in first_records
        if (snapshot_id := ablation_snapshot_id(record)) is not None
        and snapshot_id in complete_ids
        and snapshot_id in decision_by_snapshot
    )
    selected_ids = tuple(
        snapshot_id
        for record in selected_records
        if (snapshot_id := ablation_snapshot_id(record)) is not None
    )

    metrics = tuple(
        _variant_metrics(
            variant,
            selected_ids,
            prospective_by_snapshot,
            outcome_by_snapshot,
        )
        for variant in REQUIRED_ABLATION_VARIANTS
    )
    raw_ids = set(prospective_by_snapshot)
    matched_ids = raw_ids & set(decision_by_snapshot)
    structural_snapshot_count = len(structural_records)
    unique_episode_count = len(first_records)
    return EpisodeAblationReport(
        raw_snapshot_count=len(raw_ids),
        complete_snapshot_count=len(complete_ids),
        matched_snapshot_count=len(matched_ids),
        structural_snapshot_count=structural_snapshot_count,
        unique_setup_episode_count=unique_episode_count,
        selected_matured_episode_count=len(selected_ids),
        duplicate_snapshot_count=max(0, structural_snapshot_count - unique_episode_count),
        unmatched_snapshot_count=len(raw_ids - set(decision_by_snapshot)),
        variants=metrics,
    )


def report_to_jsonable(report: EpisodeAblationReport) -> dict[str, object]:
    payload = asdict(report)
    variant_rows = []
    for item in report.variants:
        row = asdict(item)
        row["variant"] = item.variant.value
        for name in (
            "total_r",
            "expectancy_r",
            "median_r",
            "max_drawdown_r",
            "total_estimated_cost_r",
            "average_estimated_cost_r",
        ):
            row[name] = str(getattr(item, name))
        variant_rows.append(row)
    payload["variants"] = variant_rows
    payload["observation_policy"] = "first_chronological_observation_per_structural_setup_episode"
    payload["research_only"] = True
    payload["execution_authority"] = False
    return payload


def _group_prospective(
    rows: Iterable[ProspectiveAblationDecision],
) -> dict[str, dict[AblationVariant, ProspectiveAblationDecision]]:
    grouped: dict[str, dict[AblationVariant, ProspectiveAblationDecision]] = {}
    for row in rows:
        bucket = grouped.setdefault(row.snapshot_id, {})
        if row.variant in bucket:
            raise ValueError(f"duplicate prospective row for {row.snapshot_id}/{row.variant.value}")
        bucket[row.variant] = row
    return grouped


def _group_outcomes(
    rows: Iterable[MaturedAblationOutcome],
) -> dict[str, dict[AblationVariant, MaturedAblationOutcome]]:
    grouped: dict[str, dict[AblationVariant, MaturedAblationOutcome]] = {}
    for row in rows:
        bucket = grouped.setdefault(row.snapshot_id, {})
        if row.variant in bucket:
            raise ValueError(f"duplicate matured row for {row.snapshot_id}/{row.variant.value}")
        bucket[row.variant] = row
    return grouped


def _has_structural_anchor(record: DecisionEvidence) -> bool:
    evidence = record.candidate_evidence
    zone_id = str(evidence.get("zone_id") or "").strip()
    liquidity_kind = str(evidence.get("liquidity_kind") or "").strip()
    liquidity_price = str(evidence.get("liquidity_price") or "").strip()
    return bool(zone_id or (liquidity_kind and liquidity_price))


def _variant_metrics(
    variant: AblationVariant,
    selected_ids: tuple[str, ...],
    prospective_by_snapshot: dict[str, dict[AblationVariant, ProspectiveAblationDecision]],
    outcome_by_snapshot: dict[str, dict[AblationVariant, MaturedAblationOutcome]],
) -> VariantEpisodeMetrics:
    values = tuple(outcome_by_snapshot[snapshot_id][variant].realized_r for snapshot_id in selected_ids)
    costs = tuple(
        outcome_by_snapshot[snapshot_id][variant].estimated_cost_r for snapshot_id in selected_ids
    )
    tradeable = sum(
        1 for snapshot_id in selected_ids if prospective_by_snapshot[snapshot_id][variant].tradeable
    )
    if not values:
        return VariantEpisodeMetrics(
            variant=variant,
            episode_count=0,
            tradeable_episode_count=0,
            wins=0,
            losses=0,
            flat=0,
            timeouts=0,
            total_r=Decimal("0"),
            expectancy_r=Decimal("0"),
            median_r=Decimal("0"),
            max_drawdown_r=Decimal("0"),
            total_estimated_cost_r=Decimal("0"),
            average_estimated_cost_r=Decimal("0"),
        )

    total_r = sum(values, Decimal("0"))
    total_cost = sum(costs, Decimal("0"))
    timeouts = sum(
        1
        for snapshot_id in selected_ids
        if outcome_by_snapshot[snapshot_id][variant].status.lower() == "timeout"
        or outcome_by_snapshot[snapshot_id][variant].exit_reason.lower() == "timeout"
    )
    return VariantEpisodeMetrics(
        variant=variant,
        episode_count=len(values),
        tradeable_episode_count=tradeable,
        wins=sum(value > 0 for value in values),
        losses=sum(value < 0 for value in values),
        flat=sum(value == 0 for value in values),
        timeouts=timeouts,
        total_r=total_r,
        expectancy_r=total_r / Decimal(len(values)),
        median_r=Decimal(str(median(values))),
        max_drawdown_r=_max_drawdown(values),
        total_estimated_cost_r=total_cost,
        average_estimated_cost_r=total_cost / Decimal(len(values)),
    )


def _max_drawdown(values: tuple[Decimal, ...]) -> Decimal:
    equity = Decimal("0")
    peak = Decimal("0")
    maximum = Decimal("0")
    for value in values:
        equity += value
        peak = max(peak, equity)
        maximum = max(maximum, peak - equity)
    return maximum
