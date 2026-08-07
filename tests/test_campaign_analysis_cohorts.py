from __future__ import annotations

import json

import pytest

from forex_trader.research.campaign_analysis import (
    CampaignBottleneck,
    aggregate_campaign,
    analyze_campaign_file,
    select_policy_cohort,
)


def row(
    fingerprint: str | None,
    *,
    campaign_id: str = "run-1",
    context: dict[str, object] | None = None,
    rejection: str = "NO_STRUCTURE_SHIFT",
) -> dict[str, object]:
    payload: dict[str, object] = {
        "campaign_id": campaign_id,
        "instruments_requested": 20,
        "instruments_evaluated": 20,
        "trade_candidates": 0,
        "abstentions": 20,
        "risk_grants": 0,
        "risk_denials": 0,
        "orders_submitted": 0,
        "orders_filled": 0,
        "orders_protected": 0,
        "orders_rejected": 0,
        "orders_cancelled": 0,
        "orders_unknown": 0,
        "orders_reconciliation_required": 0,
        "orders_emergency_close": 0,
        "orders_unresolved": 0,
        "errors": 0,
        "rejection_codes": {rejection: 20},
        "risk_denial_reasons": {},
        "error_types": {},
        "order_statuses": {},
        "promotion_ready": False,
    }
    if fingerprint is not None:
        payload["policy_fingerprint"] = fingerprint
    if context is not None:
        payload["policy_context"] = context
    return payload


def test_mixed_policy_cohorts_fail_closed_without_explicit_selector() -> None:
    records = [row("aaa", campaign_id="a"), row("bbb", campaign_id="b")]
    with pytest.raises(ValueError, match="multiple policy cohorts") as exc:
        aggregate_campaign(records)
    assert "aaa" in str(exc.value)
    assert "bbb" in str(exc.value)
    assert "--policy-fingerprint" in str(exc.value)


def test_explicit_policy_selector_analyzes_only_requested_cohort() -> None:
    records = [
        row("aaa", campaign_id="a1", rejection="NO_STRUCTURE_SHIFT"),
        row("aaa", campaign_id="a2", rejection="NO_STRUCTURE_SHIFT"),
        row("bbb", campaign_id="b1", rejection="FUNDAMENTAL_UNCALIBRATED"),
    ]
    selected, fingerprint = select_policy_cohort(records, policy_fingerprint="aaa")
    assert fingerprint == "aaa"
    assert len(selected) == 2
    aggregate = aggregate_campaign(records, policy_fingerprint="aaa")
    assert aggregate.policy_fingerprint == "aaa"
    assert aggregate.campaign_ids == ("a1", "a2")
    assert aggregate.cycles == 2
    assert aggregate.rejection_codes == {"NO_STRUCTURE_SHIFT": 40}


def test_missing_policy_selector_reports_available_cohorts() -> None:
    records = [row("aaa")]
    with pytest.raises(ValueError, match="available cohorts: aaa"):
        aggregate_campaign(records, policy_fingerprint="missing")
    with pytest.raises(ValueError, match="cannot be empty"):
        aggregate_campaign(records, policy_fingerprint="   ")


def test_same_fingerprint_with_inconsistent_policy_context_fails() -> None:
    records = [
        row("same", campaign_id="1", context={"minimum_score": "0.66"}),
        row("same", campaign_id="2", context={"minimum_score": "0.72"}),
    ]
    with pytest.raises(ValueError, match="inconsistent policy_context"):
        aggregate_campaign(records)


def test_same_context_with_different_key_order_is_consistent() -> None:
    records = [
        row("same", campaign_id="1", context={"a": 1, "nested": {"x": "y", "n": 2}}),
        row("same", campaign_id="2", context={"nested": {"n": 2, "x": "y"}, "a": 1}),
    ]
    aggregate = aggregate_campaign(records)
    assert aggregate.policy_fingerprint == "same"
    assert aggregate.campaign_ids == ("1", "2")
    assert aggregate.policy_context is not None


def test_legacy_evidence_forms_one_backward_compatible_cohort(tmp_path) -> None:
    records = [row(None, campaign_id="legacy-1") for _ in range(5)]
    aggregate = aggregate_campaign(records)
    assert aggregate.policy_fingerprint == "legacy"
    assert aggregate.policy_context is None

    path = tmp_path / "legacy.jsonl"
    path.write_text("\n".join(json.dumps(item) for item in records) + "\n", encoding="utf-8")
    diagnosis = analyze_campaign_file(path)
    assert diagnosis.aggregate.policy_fingerprint == "legacy"
    assert diagnosis.primary_bottleneck is CampaignBottleneck.STRATEGY_FORMATION


def test_analyze_campaign_file_explicitly_selects_from_mixed_jsonl(tmp_path) -> None:
    records = [
        *[row("technical", campaign_id=f"t{i}", rejection="NO_STRUCTURE_SHIFT") for i in range(5)],
        *[
            row("fundamental", campaign_id=f"f{i}", rejection="FUNDAMENTAL_UNCALIBRATED")
            for i in range(5)
        ],
    ]
    path = tmp_path / "mixed.jsonl"
    path.write_text("\n".join(json.dumps(item) for item in records) + "\n", encoding="utf-8")
    with pytest.raises(ValueError, match="multiple policy cohorts"):
        analyze_campaign_file(path)
    diagnosis = analyze_campaign_file(path, policy_fingerprint="fundamental")
    assert diagnosis.aggregate.cycles == 5
    assert diagnosis.aggregate.policy_fingerprint == "fundamental"
    assert diagnosis.primary_bottleneck is CampaignBottleneck.FUNDAMENTAL_DATA
