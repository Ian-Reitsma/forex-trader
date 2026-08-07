from __future__ import annotations

import json
from decimal import Decimal

import pytest

from forex_trader.research.campaign_analysis import (
    CampaignBottleneck,
    aggregate_campaign,
    analyze_campaign_file,
    diagnose_campaign,
    load_campaign_jsonl,
)


def cycle(
    *,
    requested: int = 20,
    evaluated: int = 20,
    candidates: int = 0,
    rejection_codes: dict[str, int] | None = None,
    risk_grants: int = 0,
    risk_denials: dict[str, int] | None = None,
    submitted: int = 0,
    filled: int = 0,
    protected: int = 0,
    rejected: int = 0,
    cancelled: int = 0,
    unknown: int = 0,
    reconciliation_required: int = 0,
    emergency_close: int = 0,
    unresolved: int | None = None,
    errors: dict[str, int] | None = None,
    order_statuses: dict[str, int] | None = None,
    promotion_ready: bool | None = False,
) -> dict[str, object]:
    rejection_codes = rejection_codes or {}
    risk_denials = risk_denials or {}
    errors = errors or {}
    abstentions = sum(rejection_codes.values())
    assert candidates + abstentions == evaluated
    if unresolved is None:
        unresolved = unknown + reconciliation_required + emergency_close
    payload: dict[str, object] = {
        "instruments_requested": requested,
        "instruments_evaluated": evaluated,
        "trade_candidates": candidates,
        "abstentions": abstentions,
        "risk_grants": risk_grants,
        "risk_denials": sum(risk_denials.values()),
        "orders_submitted": submitted,
        "orders_filled": filled,
        "orders_protected": protected,
        "orders_rejected": rejected,
        "orders_cancelled": cancelled,
        "orders_unknown": unknown,
        "orders_reconciliation_required": reconciliation_required,
        "orders_emergency_close": emergency_close,
        "orders_unresolved": unresolved,
        "errors": sum(errors.values()),
        "rejection_codes": rejection_codes,
        "risk_denial_reasons": risk_denials,
        "error_types": errors,
        "promotion_ready": promotion_ready,
    }
    if order_statuses is not None:
        payload["order_statuses"] = order_statuses
    return payload


def repeated(record: dict[str, object], count: int = 5) -> list[dict[str, object]]:
    return [dict(record) for _ in range(count)]


def test_aggregate_rates_and_promotion_readiness() -> None:
    records = repeated(
        cycle(
            candidates=2,
            rejection_codes={"NO_STRUCTURE_SHIFT": 18},
            risk_grants=2,
            submitted=1,
            protected=1,
            order_statuses={"protected": 1},
            promotion_ready=False,
        )
    )
    aggregate = aggregate_campaign(records)
    assert aggregate.cycles == 5
    assert aggregate.candidate_rate == Decimal("0.1")
    assert aggregate.evaluation_completion_rate == Decimal("1")
    assert aggregate.risk_denial_rate == 0
    assert aggregate.broker_reject_rate == 0
    assert aggregate.unresolved_rate == 0
    assert aggregate.promotion_ready_true == 0
    assert aggregate.promotion_ready_false == 5
    assert aggregate.promotion_ready_rate == 0
    assert aggregate.order_statuses == {"protected": 5}


def test_unknown_order_has_absolute_diagnostic_precedence() -> None:
    records = repeated(
        cycle(
            candidates=2,
            rejection_codes={"NO_STRUCTURE_SHIFT": 18},
            risk_grants=2,
            submitted=1,
            unknown=1,
            order_statuses={"unknown": 1},
        )
    )
    diagnosis = diagnose_campaign(aggregate_campaign(records))
    assert diagnosis.primary_bottleneck is CampaignBottleneck.EXECUTION_UNCERTAINTY
    assert diagnosis.aggregate.orders_unresolved == 5
    assert diagnosis.top_order_statuses == (("unknown", 5),)
    assert "reconcile" in diagnosis.recommendations[0].lower()


@pytest.mark.parametrize(
    ("field", "status"),
    [
        ("reconciliation_required", "reconciliation_required"),
        ("emergency_close", "emergency_close"),
    ],
)
def test_hardened_unresolved_states_have_execution_precedence(field: str, status: str) -> None:
    kwargs = {field: 1}
    records = repeated(
        cycle(
            candidates=2,
            rejection_codes={"NO_STRUCTURE_SHIFT": 18},
            risk_grants=2,
            submitted=1,
            unresolved=1,
            order_statuses={status: 1},
            **kwargs,
        )
    )
    diagnosis = diagnose_campaign(aggregate_campaign(records))
    assert diagnosis.primary_bottleneck is CampaignBottleneck.EXECUTION_UNCERTAINTY
    if field == "emergency_close":
        assert any("protection" in item.lower() for item in diagnosis.recommendations)


def test_provider_error_and_broker_rejection_precedence() -> None:
    provider = repeated(
        cycle(
            requested=20,
            evaluated=18,
            candidates=0,
            rejection_codes={"TECHNICAL_FLAT": 18},
            errors={"OandaApiError": 2},
        )
    )
    assert diagnose_campaign(aggregate_campaign(provider)).primary_bottleneck is CampaignBottleneck.PROVIDER_ERRORS

    broker = repeated(
        cycle(
            candidates=2,
            rejection_codes={"NO_STRUCTURE_SHIFT": 18},
            risk_grants=2,
            submitted=2,
            protected=1,
            rejected=1,
            order_statuses={"protected": 1, "rejected": 1},
        )
    )
    assert diagnose_campaign(aggregate_campaign(broker)).primary_bottleneck is CampaignBottleneck.BROKER_REJECTIONS

    cancelled = repeated(
        cycle(
            candidates=2,
            rejection_codes={"NO_STRUCTURE_SHIFT": 18},
            risk_grants=2,
            submitted=2,
            protected=1,
            cancelled=1,
            order_statuses={"protected": 1, "cancelled": 1},
        )
    )
    diagnosis = diagnose_campaign(aggregate_campaign(cancelled))
    assert diagnosis.primary_bottleneck is CampaignBottleneck.BROKER_REJECTIONS
    assert diagnosis.aggregate.broker_reject_rate == Decimal("0.5")


def test_fundamental_market_strategy_and_portfolio_bottlenecks() -> None:
    fundamental = repeated(cycle(rejection_codes={"FUNDAMENTAL_UNCALIBRATED": 20}))
    assert diagnose_campaign(aggregate_campaign(fundamental)).primary_bottleneck is CampaignBottleneck.FUNDAMENTAL_DATA

    context = repeated(cycle(rejection_codes={"MARKET_HOLIDAY": 12, "SPREAD_TOO_WIDE": 8}))
    assert diagnose_campaign(aggregate_campaign(context)).primary_bottleneck is CampaignBottleneck.MARKET_CONTEXT

    strategy = repeated(cycle(rejection_codes={"NO_DECLARED_LIQUIDITY_SWEEP": 12, "NO_STRUCTURE_SHIFT": 8}))
    assert diagnose_campaign(aggregate_campaign(strategy)).primary_bottleneck is CampaignBottleneck.STRATEGY_FORMATION

    portfolio = repeated(
        cycle(
            candidates=20,
            risk_denials={"signed correlation risk veto": 20},
        )
    )
    assert diagnose_campaign(aggregate_campaign(portfolio)).primary_bottleneck is CampaignBottleneck.PORTFOLIO_RISK


def test_unclassified_code_never_becomes_clean_selective() -> None:
    records = repeated(cycle(rejection_codes={"NEW_FUTURE_REJECTION": 20}))
    diagnosis = diagnose_campaign(aggregate_campaign(records))
    assert diagnosis.primary_bottleneck is CampaignBottleneck.UNCLASSIFIED_ABSTENTION
    assert any("classify" in item.lower() for item in diagnosis.recommendations)


def test_clean_selective_requires_sufficient_clean_evidence() -> None:
    records = repeated(
        cycle(
            candidates=20,
            risk_grants=20,
            submitted=1,
            protected=1,
            order_statuses={"protected": 1},
            promotion_ready=True,
        )
    )
    diagnosis = diagnose_campaign(aggregate_campaign(records))
    assert diagnosis.evidence_sufficient is True
    assert diagnosis.primary_bottleneck is CampaignBottleneck.CLEAN_SELECTIVE
    assert diagnosis.aggregate.promotion_ready_rate == 1


def test_insufficient_evidence_precedes_normal_frequency_diagnosis() -> None:
    record = cycle(rejection_codes={"NO_STRUCTURE_SHIFT": 20})
    diagnosis = diagnose_campaign(aggregate_campaign([record]))
    assert diagnosis.primary_bottleneck is CampaignBottleneck.INSUFFICIENT_EVIDENCE
    assert diagnosis.evidence_sufficient is False


def test_legacy_jsonl_without_new_unresolved_fields_remains_readable(tmp_path) -> None:
    legacy = cycle(
        candidates=2,
        rejection_codes={"NO_STRUCTURE_SHIFT": 18},
        risk_grants=2,
        submitted=1,
        unknown=1,
    )
    for key in (
        "orders_cancelled",
        "orders_reconciliation_required",
        "orders_emergency_close",
        "orders_unresolved",
    ):
        legacy.pop(key)
    diagnosis = diagnose_campaign(aggregate_campaign(repeated(legacy)))
    assert diagnosis.aggregate.orders_unknown == 5
    assert diagnosis.aggregate.orders_unresolved == 5
    assert diagnosis.primary_bottleneck is CampaignBottleneck.EXECUTION_UNCERTAINTY

    path = tmp_path / "legacy.jsonl"
    path.write_text("\n".join(json.dumps(row) for row in repeated(legacy)) + "\n", encoding="utf-8")
    assert analyze_campaign_file(path).primary_bottleneck is CampaignBottleneck.EXECUTION_UNCERTAINTY


def test_jsonl_loader_and_file_analysis(tmp_path) -> None:
    path = tmp_path / "evidence.jsonl"
    rows = repeated(cycle(rejection_codes={"FUNDAMENTAL_UNCALIBRATED": 20}))
    path.write_text("\n".join(json.dumps(row) for row in rows) + "\n", encoding="utf-8")
    assert len(load_campaign_jsonl(path)) == 5
    diagnosis = analyze_campaign_file(path)
    assert diagnosis.primary_bottleneck is CampaignBottleneck.FUNDAMENTAL_DATA
    payload = diagnosis.to_jsonable()
    assert payload["aggregate"]["cycles"] == 5  # type: ignore[index]


def test_jsonl_loader_rejects_missing_empty_invalid_and_non_object(tmp_path) -> None:
    with pytest.raises(FileNotFoundError):
        load_campaign_jsonl(tmp_path / "missing.jsonl")

    empty = tmp_path / "empty.jsonl"
    empty.write_text("\n", encoding="utf-8")
    with pytest.raises(ValueError, match="no cycle records"):
        load_campaign_jsonl(empty)

    invalid = tmp_path / "invalid.jsonl"
    invalid.write_text("{not-json}\n", encoding="utf-8")
    with pytest.raises(ValueError, match="invalid campaign JSONL line 1"):
        load_campaign_jsonl(invalid)

    non_object = tmp_path / "array.jsonl"
    non_object.write_text("[]\n", encoding="utf-8")
    with pytest.raises(ValueError, match="expected object"):
        load_campaign_jsonl(non_object)


def test_aggregate_rejects_internally_impossible_records() -> None:
    bad = cycle(rejection_codes={"NO_STRUCTURE_SHIFT": 20})
    bad["instruments_evaluated"] = 21
    with pytest.raises(ValueError, match="evaluated more instruments"):
        aggregate_campaign([bad])

    bad = cycle(candidates=2, rejection_codes={"NO_STRUCTURE_SHIFT": 18}, risk_grants=2)
    bad["orders_submitted"] = 3
    with pytest.raises(ValueError, match="submitted orders exceed risk grants"):
        aggregate_campaign([bad])

    bad = cycle(
        candidates=2,
        rejection_codes={"NO_STRUCTURE_SHIFT": 18},
        risk_grants=2,
        submitted=1,
        protected=1,
    )
    bad["orders_unknown"] = 1
    bad["orders_unresolved"] = 1
    with pytest.raises(ValueError, match="known order outcomes exceed submissions"):
        aggregate_campaign([bad])

    bad = cycle(
        candidates=2,
        rejection_codes={"NO_STRUCTURE_SHIFT": 18},
        risk_grants=2,
        submitted=1,
        protected=1,
        order_statuses={"filled": 1},
    )
    with pytest.raises(ValueError, match="order-status protected"):
        aggregate_campaign([bad])

    bad = cycle(
        candidates=2,
        rejection_codes={"NO_STRUCTURE_SHIFT": 18},
        risk_grants=2,
        submitted=1,
        unknown=1,
        unresolved=0,
        order_statuses={"unknown": 1},
    )
    with pytest.raises(ValueError, match="orders_unknown exceeds unresolved"):
        aggregate_campaign([bad])


def test_aggregate_rejects_bad_types_counts_and_readiness() -> None:
    bad = cycle(rejection_codes={"NO_STRUCTURE_SHIFT": 20})
    bad["errors"] = True
    with pytest.raises(ValueError, match="must be an integer"):
        aggregate_campaign([bad])

    bad = cycle(rejection_codes={"NO_STRUCTURE_SHIFT": 20})
    bad["instruments_requested"] = 20.5
    with pytest.raises(ValueError, match="must be an integer"):
        aggregate_campaign([bad])

    bad = cycle(rejection_codes={"NO_STRUCTURE_SHIFT": 20})
    bad["promotion_ready"] = "no"
    with pytest.raises(ValueError, match="boolean or null"):
        aggregate_campaign([bad])

    bad = cycle(rejection_codes={"NO_STRUCTURE_SHIFT": 20})
    bad["order_statuses"] = []
    with pytest.raises(ValueError, match="order_statuses must be an object"):
        aggregate_campaign([bad])


def test_diagnosis_validates_minimum_evidence_thresholds() -> None:
    aggregate = aggregate_campaign([cycle(rejection_codes={"NO_STRUCTURE_SHIFT": 20})])
    with pytest.raises(ValueError, match="must be positive"):
        diagnose_campaign(aggregate, minimum_cycles=0)
    with pytest.raises(ValueError, match="must be positive"):
        diagnose_campaign(aggregate, minimum_evaluations=0)
