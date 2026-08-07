from __future__ import annotations

import json
from collections import Counter
from dataclasses import dataclass
from decimal import Decimal
from enum import StrEnum
from pathlib import Path
from typing import Iterable, Mapping


class CampaignBottleneck(StrEnum):
    INSUFFICIENT_EVIDENCE = "insufficient_evidence"
    EXECUTION_UNCERTAINTY = "execution_uncertainty"
    BROKER_REJECTIONS = "broker_rejections"
    PROVIDER_ERRORS = "provider_errors"
    FUNDAMENTAL_DATA = "fundamental_data"
    MARKET_CONTEXT = "market_context"
    STRATEGY_FORMATION = "strategy_formation"
    PORTFOLIO_RISK = "portfolio_risk"
    UNCLASSIFIED_ABSTENTION = "unclassified_abstention"
    CLEAN_SELECTIVE = "clean_selective"


_UNRESOLVED_STATUS_NAMES = {
    "created",
    "acknowledged",
    "partially_filled",
    "unknown",
    "reconciliation_required",
    "closing",
    "emergency_close",
}


@dataclass(frozen=True, slots=True)
class CampaignAggregate:
    cycles: int
    instruments_requested: int
    instruments_evaluated: int
    trade_candidates: int
    abstentions: int
    risk_grants: int
    risk_denials: int
    orders_submitted: int
    orders_filled: int
    orders_protected: int
    orders_rejected: int
    orders_cancelled: int
    orders_unknown: int
    orders_reconciliation_required: int
    orders_emergency_close: int
    orders_unresolved: int
    errors: int
    promotion_ready_true: int
    promotion_ready_false: int
    promotion_ready_unknown: int
    rejection_codes: dict[str, int]
    risk_denial_reasons: dict[str, int]
    error_types: dict[str, int]
    order_statuses: dict[str, int]

    @property
    def candidate_rate(self) -> Decimal:
        return _rate(self.trade_candidates, self.instruments_evaluated)

    @property
    def evaluation_completion_rate(self) -> Decimal:
        return _rate(self.instruments_evaluated, self.instruments_requested)

    @property
    def risk_denial_rate(self) -> Decimal:
        return _rate(self.risk_denials, self.trade_candidates)

    @property
    def broker_reject_rate(self) -> Decimal:
        return _rate(self.orders_rejected + self.orders_cancelled, self.orders_submitted)

    @property
    def unknown_rate(self) -> Decimal:
        return _rate(self.orders_unknown, self.orders_submitted)

    @property
    def unresolved_rate(self) -> Decimal:
        return _rate(self.orders_unresolved, self.orders_submitted)

    @property
    def error_rate(self) -> Decimal:
        return _rate(self.errors, self.instruments_requested)

    @property
    def promotion_ready_rate(self) -> Decimal:
        observed = self.promotion_ready_true + self.promotion_ready_false
        return _rate(self.promotion_ready_true, observed)


@dataclass(frozen=True, slots=True)
class CampaignDiagnosis:
    aggregate: CampaignAggregate
    primary_bottleneck: CampaignBottleneck
    evidence_sufficient: bool
    category_counts: dict[str, int]
    top_rejection_codes: tuple[tuple[str, int], ...]
    top_risk_denials: tuple[tuple[str, int], ...]
    top_error_types: tuple[tuple[str, int], ...]
    top_order_statuses: tuple[tuple[str, int], ...]
    recommendations: tuple[str, ...]

    def to_jsonable(self) -> dict[str, object]:
        return {
            "aggregate": {
                "cycles": self.aggregate.cycles,
                "instruments_requested": self.aggregate.instruments_requested,
                "instruments_evaluated": self.aggregate.instruments_evaluated,
                "trade_candidates": self.aggregate.trade_candidates,
                "abstentions": self.aggregate.abstentions,
                "risk_grants": self.aggregate.risk_grants,
                "risk_denials": self.aggregate.risk_denials,
                "orders_submitted": self.aggregate.orders_submitted,
                "orders_filled": self.aggregate.orders_filled,
                "orders_protected": self.aggregate.orders_protected,
                "orders_rejected": self.aggregate.orders_rejected,
                "orders_cancelled": self.aggregate.orders_cancelled,
                "orders_unknown": self.aggregate.orders_unknown,
                "orders_reconciliation_required": self.aggregate.orders_reconciliation_required,
                "orders_emergency_close": self.aggregate.orders_emergency_close,
                "orders_unresolved": self.aggregate.orders_unresolved,
                "errors": self.aggregate.errors,
                "promotion_ready_true": self.aggregate.promotion_ready_true,
                "promotion_ready_false": self.aggregate.promotion_ready_false,
                "promotion_ready_unknown": self.aggregate.promotion_ready_unknown,
                "candidate_rate": str(self.aggregate.candidate_rate),
                "evaluation_completion_rate": str(self.aggregate.evaluation_completion_rate),
                "risk_denial_rate": str(self.aggregate.risk_denial_rate),
                "broker_reject_rate": str(self.aggregate.broker_reject_rate),
                "unknown_rate": str(self.aggregate.unknown_rate),
                "unresolved_rate": str(self.aggregate.unresolved_rate),
                "error_rate": str(self.aggregate.error_rate),
                "promotion_ready_rate": str(self.aggregate.promotion_ready_rate),
            },
            "primary_bottleneck": self.primary_bottleneck.value,
            "evidence_sufficient": self.evidence_sufficient,
            "category_counts": dict(self.category_counts),
            "top_rejection_codes": [list(item) for item in self.top_rejection_codes],
            "top_risk_denials": [list(item) for item in self.top_risk_denials],
            "top_error_types": [list(item) for item in self.top_error_types],
            "top_order_statuses": [list(item) for item in self.top_order_statuses],
            "recommendations": list(self.recommendations),
        }


_STRATEGY_REJECTIONS = {
    "TECHNICAL_FLAT",
    "NO_DECLARED_LIQUIDITY_SWEEP",
    "NO_STRUCTURE_SHIFT",
    "SETUP_NOT_ENTRY_READY",
    "LOCATION_LOW_QUALITY",
    "NO_DISPLACEMENT",
    "NO_STRUCTURAL_TARGET",
    "INSUFFICIENT_NET_REWARD",
    "SCORE_BELOW_POLICY",
}
_FUNDAMENTAL_REJECTIONS = {
    "FUNDAMENTAL_UNCALIBRATED",
    "FUNDAMENTAL_CONFLICT",
}
_CONTEXT_REJECTIONS = {
    "EVENT_BLACKOUT",
    "MARKET_HOLIDAY",
    "ROLLOVER_BLACKOUT",
    "QUOTE_STALE",
    "SPREAD_TOO_WIDE",
    "CANDIDATE_EXPIRED",
    "LATE_ENTRY",
}

_NUMERIC_FIELDS = (
    "instruments_requested",
    "instruments_evaluated",
    "trade_candidates",
    "abstentions",
    "risk_grants",
    "risk_denials",
    "orders_submitted",
    "orders_filled",
    "orders_protected",
    "orders_rejected",
    "orders_cancelled",
    "orders_unknown",
    "orders_reconciliation_required",
    "orders_emergency_close",
    "orders_unresolved",
    "errors",
)


def load_campaign_jsonl(path: str | Path) -> list[dict[str, object]]:
    file_path = Path(path)
    if not file_path.is_file():
        raise FileNotFoundError(file_path)
    records: list[dict[str, object]] = []
    for line_number, raw in enumerate(file_path.read_text(encoding="utf-8").splitlines(), start=1):
        if not raw.strip():
            continue
        try:
            item = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise ValueError(f"invalid campaign JSONL line {line_number}: {exc.msg}") from exc
        if not isinstance(item, dict):
            raise ValueError(f"invalid campaign JSONL line {line_number}: expected object")
        records.append(item)
    if not records:
        raise ValueError("campaign evidence file contains no cycle records")
    return records


def aggregate_campaign(records: Iterable[Mapping[str, object]]) -> CampaignAggregate:
    records = tuple(records)
    if not records:
        raise ValueError("at least one campaign cycle is required")
    rejection_codes: Counter[str] = Counter()
    risk_denials: Counter[str] = Counter()
    error_types: Counter[str] = Counter()
    order_statuses: Counter[str] = Counter()
    totals = Counter[str]()
    promotion = Counter[str]()

    for index, record in enumerate(records, start=1):
        values = {
            field: _nonnegative_int(record.get(field, 0), field=field, cycle=index)
            for field in _NUMERIC_FIELDS
        }
        _validate_cycle(values, record, index)
        totals.update(values)
        rejection_codes.update(_counter_mapping(record.get("rejection_codes"), "rejection_codes", index))
        risk_denials.update(_counter_mapping(record.get("risk_denial_reasons"), "risk_denial_reasons", index))
        error_types.update(_counter_mapping(record.get("error_types"), "error_types", index))
        order_statuses.update(_counter_mapping(record.get("order_statuses"), "order_statuses", index))
        readiness = record.get("promotion_ready")
        if readiness is True:
            promotion["true"] += 1
        elif readiness is False:
            promotion["false"] += 1
        elif readiness is None:
            promotion["unknown"] += 1
        else:
            raise ValueError(f"campaign cycle {index} field promotion_ready must be boolean or null")

    if sum(rejection_codes.values()) != totals["abstentions"]:
        raise ValueError("campaign rejection-code totals do not match aggregate abstentions")
    if sum(risk_denials.values()) != totals["risk_denials"]:
        raise ValueError("campaign risk-denial totals do not match aggregate risk denials")
    if sum(error_types.values()) != totals["errors"]:
        raise ValueError("campaign error-type totals do not match aggregate errors")

    return CampaignAggregate(
        cycles=len(records),
        instruments_requested=totals["instruments_requested"],
        instruments_evaluated=totals["instruments_evaluated"],
        trade_candidates=totals["trade_candidates"],
        abstentions=totals["abstentions"],
        risk_grants=totals["risk_grants"],
        risk_denials=totals["risk_denials"],
        orders_submitted=totals["orders_submitted"],
        orders_filled=totals["orders_filled"],
        orders_protected=totals["orders_protected"],
        orders_rejected=totals["orders_rejected"],
        orders_cancelled=totals["orders_cancelled"],
        orders_unknown=totals["orders_unknown"],
        orders_reconciliation_required=totals["orders_reconciliation_required"],
        orders_emergency_close=totals["orders_emergency_close"],
        orders_unresolved=totals["orders_unresolved"],
        errors=totals["errors"],
        promotion_ready_true=promotion["true"],
        promotion_ready_false=promotion["false"],
        promotion_ready_unknown=promotion["unknown"],
        rejection_codes=dict(rejection_codes),
        risk_denial_reasons=dict(risk_denials),
        error_types=dict(error_types),
        order_statuses=dict(order_statuses),
    )


def diagnose_campaign(
    aggregate: CampaignAggregate,
    *,
    minimum_cycles: int = 5,
    minimum_evaluations: int = 100,
) -> CampaignDiagnosis:
    if minimum_cycles < 1 or minimum_evaluations < 1:
        raise ValueError("minimum evidence thresholds must be positive")
    evidence_sufficient = (
        aggregate.cycles >= minimum_cycles
        and aggregate.instruments_evaluated >= minimum_evaluations
    )
    categories = Counter[str]()
    for code, count in aggregate.rejection_codes.items():
        if code in _STRATEGY_REJECTIONS:
            categories[CampaignBottleneck.STRATEGY_FORMATION.value] += count
        elif code in _FUNDAMENTAL_REJECTIONS:
            categories[CampaignBottleneck.FUNDAMENTAL_DATA.value] += count
        elif code in _CONTEXT_REJECTIONS:
            categories[CampaignBottleneck.MARKET_CONTEXT.value] += count
        else:
            categories[CampaignBottleneck.UNCLASSIFIED_ABSTENTION.value] += count
    categories[CampaignBottleneck.PORTFOLIO_RISK.value] += aggregate.risk_denials
    categories[CampaignBottleneck.BROKER_REJECTIONS.value] += aggregate.orders_rejected + aggregate.orders_cancelled
    categories[CampaignBottleneck.EXECUTION_UNCERTAINTY.value] += aggregate.orders_unresolved
    categories[CampaignBottleneck.PROVIDER_ERRORS.value] += aggregate.errors

    primary = _primary_bottleneck(aggregate, categories, evidence_sufficient)
    recommendations = _recommendations(aggregate, categories, primary, evidence_sufficient)
    return CampaignDiagnosis(
        aggregate=aggregate,
        primary_bottleneck=primary,
        evidence_sufficient=evidence_sufficient,
        category_counts=dict(categories),
        top_rejection_codes=tuple(Counter(aggregate.rejection_codes).most_common(8)),
        top_risk_denials=tuple(Counter(aggregate.risk_denial_reasons).most_common(8)),
        top_error_types=tuple(Counter(aggregate.error_types).most_common(8)),
        top_order_statuses=tuple(Counter(aggregate.order_statuses).most_common(8)),
        recommendations=tuple(recommendations),
    )


def analyze_campaign_file(
    path: str | Path,
    *,
    minimum_cycles: int = 5,
    minimum_evaluations: int = 100,
) -> CampaignDiagnosis:
    return diagnose_campaign(
        aggregate_campaign(load_campaign_jsonl(path)),
        minimum_cycles=minimum_cycles,
        minimum_evaluations=minimum_evaluations,
    )


def _primary_bottleneck(
    aggregate: CampaignAggregate,
    categories: Counter[str],
    evidence_sufficient: bool,
) -> CampaignBottleneck:
    if aggregate.orders_unresolved > 0:
        return CampaignBottleneck.EXECUTION_UNCERTAINTY
    if aggregate.errors > 0 and aggregate.error_rate >= Decimal("0.05"):
        return CampaignBottleneck.PROVIDER_ERRORS
    if (
        aggregate.orders_rejected + aggregate.orders_cancelled > 0
        and aggregate.broker_reject_rate >= Decimal("0.05")
    ):
        return CampaignBottleneck.BROKER_REJECTIONS
    if not evidence_sufficient:
        return CampaignBottleneck.INSUFFICIENT_EVIDENCE
    ordered = (
        CampaignBottleneck.UNCLASSIFIED_ABSTENTION,
        CampaignBottleneck.FUNDAMENTAL_DATA,
        CampaignBottleneck.MARKET_CONTEXT,
        CampaignBottleneck.STRATEGY_FORMATION,
        CampaignBottleneck.PORTFOLIO_RISK,
    )
    winner = max(ordered, key=lambda item: categories.get(item.value, 0))
    if categories.get(winner.value, 0) > 0:
        return winner
    return CampaignBottleneck.CLEAN_SELECTIVE


def _recommendations(
    aggregate: CampaignAggregate,
    categories: Counter[str],
    primary: CampaignBottleneck,
    evidence_sufficient: bool,
) -> list[str]:
    recommendations: list[str] = []
    if primary is CampaignBottleneck.EXECUTION_UNCERTAINTY:
        recommendations.append(
            "Stop new Practice risk and reconcile broker orders/trades before any further submissions. Protection/reconciliation/partial/ambiguous states outrank strategy tuning."
        )
    if aggregate.orders_emergency_close > 0:
        recommendations.append(
            "Emergency-close evidence means dependent protection could not be verified. Resolve broker protection behavior before any additional Practice risk."
        )
    if primary is CampaignBottleneck.PROVIDER_ERRORS:
        recommendations.append(
            "Resolve provider/authentication/market-data errors before strategy optimization; repeated failed evaluations are not strategy evidence."
        )
    if primary is CampaignBottleneck.BROKER_REJECTIONS:
        recommendations.append(
            "Inspect OANDA reject/cancel payloads, instrument metadata, protection distances and unit/price precision before changing strategy thresholds."
        )
    if primary is CampaignBottleneck.UNCLASSIFIED_ABSTENTION:
        recommendations.append(
            "A new/unknown abstention code dominates. Classify its semantics and add a tested analyzer mapping before drawing optimization conclusions."
        )
    if not evidence_sufficient:
        recommendations.append(
            "Collect more independent campaign cycles/evaluations before treating rejection frequencies as stable."
        )
    if categories.get(CampaignBottleneck.FUNDAMENTAL_DATA.value, 0):
        recommendations.append(
            "If FUNDAMENTAL_UNCALIBRATED dominates, improve legitimate point-in-time macro/news coverage rather than disabling the fundamental gate."
        )
    if categories.get(CampaignBottleneck.MARKET_CONTEXT.value, 0):
        recommendations.append(
            "Treat event, holiday, rollover, spread and late-entry abstentions as execution/context evidence; do not compensate by widening risk or forcing entries."
        )
    if categories.get(CampaignBottleneck.STRATEGY_FORMATION.value, 0):
        recommendations.append(
            "For sweep/structure/location abstentions, inspect whether the declared liquidity/zone model is missing a legitimate feature. Do not lower quality gates solely to increase trade count."
        )
    if categories.get(CampaignBottleneck.PORTFOLIO_RISK.value, 0):
        recommendations.append(
            "Portfolio-risk denials mean an isolated setup is not acceptable account risk; inspect clustering/currency/margin exposure before considering limit changes."
        )
    if aggregate.orders_submitted == 0:
        recommendations.append(
            "Zero submitted orders is not itself a failure. Diagnose candidate, risk and context bottlenecks before changing any production policy."
        )
    if aggregate.promotion_ready_true == 0 and aggregate.promotion_ready_false > 0:
        recommendations.append(
            "The promotion gate has never reported ready in observed cycles; use its concrete blockers and realized outcome metrics before proposing any production promotion."
        )
    if evidence_sufficient and primary is CampaignBottleneck.CLEAN_SELECTIVE:
        recommendations.append(
            "Operational evidence is clean but selective. Continue the Practice campaign and evaluate realized trade outcomes/promotion metrics before strategy changes."
        )
    return recommendations


def _validate_cycle(values: Mapping[str, int], record: Mapping[str, object], cycle: int) -> None:
    requested = values["instruments_requested"]
    evaluated = values["instruments_evaluated"]
    candidates = values["trade_candidates"]
    abstentions = values["abstentions"]
    grants = values["risk_grants"]
    denials = values["risk_denials"]
    submitted = values["orders_submitted"]
    known_outcomes = (
        values["orders_filled"]
        + values["orders_protected"]
        + values["orders_rejected"]
        + values["orders_cancelled"]
        + values["orders_unknown"]
        + values["orders_reconciliation_required"]
        + values["orders_emergency_close"]
    )
    if evaluated > requested:
        raise ValueError(f"campaign cycle {cycle} evaluated more instruments than requested")
    if candidates + abstentions != evaluated:
        raise ValueError(f"campaign cycle {cycle} candidates + abstentions must equal evaluated")
    if grants + denials > candidates:
        raise ValueError(f"campaign cycle {cycle} risk decisions exceed trade candidates")
    if submitted > grants:
        raise ValueError(f"campaign cycle {cycle} submitted orders exceed risk grants")
    if known_outcomes > submitted:
        raise ValueError(f"campaign cycle {cycle} known order outcomes exceed submissions")
    if values["orders_unresolved"] > submitted:
        raise ValueError(f"campaign cycle {cycle} unresolved orders exceed submissions")
    for field in ("orders_unknown", "orders_reconciliation_required", "orders_emergency_close"):
        if values[field] > values["orders_unresolved"]:
            raise ValueError(f"campaign cycle {cycle} {field} exceeds unresolved orders")

    rejections = _counter_mapping(record.get("rejection_codes"), "rejection_codes", cycle)
    risk_reasons = _counter_mapping(record.get("risk_denial_reasons"), "risk_denial_reasons", cycle)
    errors = _counter_mapping(record.get("error_types"), "error_types", cycle)
    statuses = _counter_mapping(record.get("order_statuses"), "order_statuses", cycle)
    if sum(rejections.values()) != abstentions:
        raise ValueError(f"campaign cycle {cycle} rejection-code counts must equal abstentions")
    if sum(risk_reasons.values()) != denials:
        raise ValueError(f"campaign cycle {cycle} risk-denial counts must equal risk denials")
    if sum(errors.values()) != values["errors"]:
        raise ValueError(f"campaign cycle {cycle} error-type counts must equal errors")
    if statuses:
        if sum(statuses.values()) != submitted:
            raise ValueError(f"campaign cycle {cycle} order-status counts must equal submissions")
        expected = {
            "filled": values["orders_filled"],
            "protected": values["orders_protected"],
            "rejected": values["orders_rejected"],
            "cancelled": values["orders_cancelled"],
            "unknown": values["orders_unknown"],
            "reconciliation_required": values["orders_reconciliation_required"],
            "emergency_close": values["orders_emergency_close"],
        }
        for status_name, count in expected.items():
            if statuses.get(status_name, 0) != count:
                raise ValueError(
                    f"campaign cycle {cycle} order-status {status_name} does not match its explicit counter"
                )
        unresolved_from_status = sum(
            count for status_name, count in statuses.items() if status_name in _UNRESOLVED_STATUS_NAMES
        )
        if unresolved_from_status != values["orders_unresolved"]:
            raise ValueError(
                f"campaign cycle {cycle} unresolved order-status counts do not match orders_unresolved"
            )


def _rate(numerator: int, denominator: int) -> Decimal:
    return Decimal("0") if denominator <= 0 else Decimal(numerator) / Decimal(denominator)


def _nonnegative_int(value: object, *, field: str, cycle: int) -> int:
    if isinstance(value, bool):
        raise ValueError(f"campaign cycle {cycle} field {field} must be an integer")
    if isinstance(value, float) and not value.is_integer():
        raise ValueError(f"campaign cycle {cycle} field {field} must be an integer")
    try:
        parsed = int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"campaign cycle {cycle} field {field} must be an integer") from exc
    if parsed < 0:
        raise ValueError(f"campaign cycle {cycle} field {field} cannot be negative")
    return parsed


def _counter_mapping(value: object, field: str, cycle: int) -> Counter[str]:
    if value is None:
        return Counter()
    if not isinstance(value, Mapping):
        raise ValueError(f"campaign cycle {cycle} field {field} must be an object")
    result: Counter[str] = Counter()
    for key, count in value.items():
        parsed = _nonnegative_int(count, field=f"{field}.{key}", cycle=cycle)
        result[str(key)] += parsed
    return result
