from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from forex_trader.application.campaign import PracticeCampaignRunner
from forex_trader.domain.enums import DecisionDisposition


class AbstainEngine:
    def evaluate(self, instrument: str, *, execute: bool = False):  # type: ignore[no-untyped-def]
        return SimpleNamespace(
            candidate=SimpleNamespace(
                disposition=DecisionDisposition.ABSTAIN,
                rejection_code="NO_STRUCTURE_SHIFT",
            ),
            risk=None,
            order=None,
        )

    def promotion_status(self):  # type: ignore[no-untyped-def]
        return {"ready": False}


def test_campaign_persists_stable_policy_cohort_across_cycles(tmp_path) -> None:
    evidence = tmp_path / "campaign.jsonl"
    context = {
        "schema": "campaign-policy-v1",
        "strategy": {"minimum_score": "0.66"},
        "campaign": {"execute": False, "max_new_orders_per_cycle": 0},
    }
    runner = PracticeCampaignRunner(
        AbstainEngine(),  # type: ignore[arg-type]
        ["EUR_USD"],
        execute=False,
        max_new_orders_per_cycle=0,
        evidence_path=evidence,
        campaign_id="cohort-run-1",
        policy_context=context,
        campaign_metadata={"universe_source": "configured"},
    )
    report = runner.run(max_cycles=2, interval_seconds=0)
    assert len(report.cycles) == 2
    assert {cycle.campaign_id for cycle in report.cycles} == {"cohort-run-1"}
    assert {cycle.policy_fingerprint for cycle in report.cycles} == {runner.policy_fingerprint}
    assert all(cycle.policy_context == context for cycle in report.cycles)

    rows = [json.loads(line) for line in evidence.read_text(encoding="utf-8").splitlines()]
    assert len(rows) == 2
    assert {row["policy_fingerprint"] for row in rows} == {runner.policy_fingerprint}
    assert {row["campaign_id"] for row in rows} == {"cohort-run-1"}
    assert rows[0]["campaign_metadata"] == {"universe_source": "configured"}


def test_campaign_fallback_policy_context_is_stable_for_minimal_test_engine() -> None:
    engine = AbstainEngine()
    first = PracticeCampaignRunner(engine, ["EUR_USD"], execute=False, campaign_id="first")  # type: ignore[arg-type]
    second = PracticeCampaignRunner(engine, ["EUR_USD"], execute=False, campaign_id="second")  # type: ignore[arg-type]
    assert first.policy_context["policy_introspection"] == "unavailable"
    assert first.policy_fingerprint == second.policy_fingerprint


def test_campaign_policy_change_changes_fingerprint() -> None:
    engine = AbstainEngine()
    first = PracticeCampaignRunner(  # type: ignore[arg-type]
        engine,
        ["EUR_USD"],
        execute=False,
        policy_context={"schema": "campaign-policy-v1", "minimum_score": "0.66"},
    )
    second = PracticeCampaignRunner(  # type: ignore[arg-type]
        engine,
        ["EUR_USD"],
        execute=False,
        policy_context={"schema": "campaign-policy-v1", "minimum_score": "0.72"},
    )
    assert first.policy_fingerprint != second.policy_fingerprint


def test_campaign_rejects_empty_explicit_campaign_id() -> None:
    with pytest.raises(ValueError, match="campaign_id cannot be empty"):
        PracticeCampaignRunner(  # type: ignore[arg-type]
            AbstainEngine(), ["EUR_USD"], execute=False, campaign_id="   "
        )
