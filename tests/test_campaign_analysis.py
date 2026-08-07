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


def test_aggregate_rates_statuses_and_promotion_readiness() -> None:
    aggregate = aggregate_campaign(
        repeated(
            cycle(
                candidates=2,
                rejection_codes={"NO_STRUCTURE_SHIFT": 18},
                risk_grants=2,
                submitted=1,
                protected=1,
                order_statuses={"protected": 1},
            )
        )
    )
    assert aggregate.cycles == 5
    assert aggregate.candidate_rate == Decimal("0.1")
    assert aggregate.evaluation_completion_rate == 1
    assert aggregate.risk_denial_rate == 0
    assert aggregate.broker_reject_rate == 0
    assert aggregate.unresolved_rate == 0
    assert aggregate.promotion_ready_false == 5
    assert aggregate.promotion_ready_rate == 0
    assert aggregate.order_statuses == {"protected": 5}


@pytest.mark.parametrize(
    ("kwargs", "status"),
    [
        ({"unknown": 1}, "unknown"),
        ({"reconciliation_required": 1}, "reconciliation_required"),
        ({"emergency_close": 1}, "emergency_close"),
    ],
)
def test_unresolved_broker_states_have_absolute_diagnostic_precedence(
    kwargs: dict[str, int], status: str
) -> None:
    diagnosis = diagnose_campaign(
        aggregate_campaign(
            repeated(
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
        )
    )
    assert diagnosis.primary_bottleneck is CampaignBottleneck.EXECUTION_UNCERTAINTY
    assert diagnosis.aggregate.orders_unresolved == 5
    assert diagnosis.top_order_statuses == ((status, 5),)
    assert "reconcile" in diagnosis.recommendations[0].lower()
    if status == "emergency_close":
        assert any("protection" in item.lower() for item in diagnosis.recommendations)


def test_provider_errors_and_broker_reject_cancel_precede_strategy() -> None:
    provider = repeated(
        cycle(
            requested=20,
            evaluated=18,
            rejection_codes={"TECHNICAL_FLAT": 18},
            errors={"OandaApiError": 2},
        )
    )
    assert diagnose_campaign(aggregate_campaign(provider)).primary_bottleneck is CampaignBottleneck.PROVIDER_ERRORS

    for field, status in (("rejected", "rejected"), ("cancelled", "cancelled")):
        kwargs = {field: 1}
        diagnosis = diagnose_campaign(
            aggregate_campaign(
                repeated(
                    cycle(
                        candidates=2,
                        rejection_codes={"NO_STRUCTURE_SHIFT": 18},
                        risk_grants=2,
                        submitted=2,
                        protected=1,
                        order_statuses={"protected": 1, status: 1},
                        **kwargs,
                    )
                )
            )
        )
        assert diagnosis.primary_bottleneck is CampaignBottleneck.BROKER_REJECTIONS
        assert diagnosis.aggregate.broker_reject_rate == Decimal("0.5")


@pytest.mark.parametrize(
    ("code", "expected"),
    [
        ("FUNDAMENTAL_UNCALIBRATED", CampaignBottleneck.FUNDAMENTAL_DATA),
        ("MARKET_HOLIDAY", CampaignBottleneck.MARKET_CONTEXT),
        ("NO_DECLARED_LIQUIDITY_SWEEP", CampaignBottleneck.STRATEGY_FORMATION),
        ("NEW_FUTURE_REJECTION", CampaignBottleneck.UNCLASSIFIED_ABSTENTION),
    ],
)
def test_rejection_categories_are_explicit(code: str, expected: CampaignBottleneck) -> None:
    diagnosis = diagnose_campaign(aggregate_campaign(repeated(cycle(rejection_codes={code: 20}))))
    assert diagnosis.primary_bottleneck is expected
    if expected is CampaignBottleneck.UNCLASSIFIED_ABSTENTION:
        assert any("classify" in item.lower() for item in diagnosis.recommendations)


def test_portfolio_risk_and_clean_selective_diagnoses() -> None:
    portfolio = repeated(cycle(candidates=20, risk_denials={"signed correlation risk veto": 20}))
    assert diagnose_campaign(aggregate_campaign(portfolio)).primary_bottleneck is CampaignBottleneck.PORTFOLIO_RISK

    clean = repeated(
        cycle(
            candidates=20,
            risk_grants=20,
            submitted=1,
            protected=1,
            order_statuses={"protected": 1},
            promotion_ready=True,
        )
    )
    diagnosis = diagnose_campaign(aggregate_campaign(clean))
    assert diagnosis.evidence_sufficient is True
    assert diagnosis.primary_bottleneck is CampaignBottleneck.CLEAN_SELECTIVE
    assert diagnosis.aggregate.promotion_ready_rate == 1


def test_insufficient_evidence_precedes_normal_frequency_diagnosis() -> None:
    diagnosis = diagnose_campaign(
        aggregate_campaign([cycle(rejection_codes={"NO_STRUCTURE_SHIFT": 20})])
    )
    assert diagnosis.primary_bottleneck is CampaignBottleneck.INSUFFICIENT_EVIDENCE
    assert diagnosis.evidence_sufficient is False


def test_legacy_unknown_evidence_infers_unresolved_and_file_analysis(tmp_path) -> None:
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
    aggregate = aggregate_campaign(repeated(legacy))
    assert aggregate.orders_unknown == 5
    assert aggregate.orders_unresolved == 5

    path = tmp_path / "legacy.jsonl"
    path.write_text("\n".join(json.dumps(row) for row in repeated(legacy)) + "\n", encoding="utf-8")
    diagnosis = analyze_campaign_file(path)
    assert diagnosis.primary_bottleneck is CampaignBottleneck.EXECUTION_UNCERTAINTY
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


def test_aggregate_rejects_impossible_accounting_and_histograms() -> None:
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
        order_statuses={"created": 1},
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


def test_aggregate_rejects_bad_types_and_diagnosis_thresholds() -> None:
    for field, value, pattern in (
        ("errors", True, "must be an integer"),
        ("instruments_requested", 20.5, "must be an integer"),
        ("promotion_ready", "no", "boolean or null"),
        ("order_statuses", [], "must be an object"),
    ):
        bad = cycle(rejection_codes={"NO_STRUCTURE_SHIFT": 20})
        bad[field] = value
        with pytest.raises(ValueError, match=pattern):
            aggregate_campaign([bad])

    aggregate = aggregate_campaign([cycle(rejection_codes={"NO_STRUCTURE_SHIFT": 20})])
    with pytest.raises(ValueError, match="must be positive"):
        diagnose_campaign(aggregate, minimum_cycles=0)
    with pytest.raises(ValueError, match="must be positive"):
        diagnose_campaign(aggregate, minimum_evaluations=0)
