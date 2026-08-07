from __future__ import annotations

from pathlib import Path

import yaml


WORKFLOW = Path(".github/workflows/practice-validation.yml")


def _workflow() -> dict[str, object]:
    payload = yaml.load(WORKFLOW.read_text(encoding="utf-8"), Loader=yaml.BaseLoader)
    assert isinstance(payload, dict)
    return payload


def test_practice_validation_is_manual_only() -> None:
    workflow = _workflow()
    triggers = workflow["on"]
    assert isinstance(triggers, dict)
    assert set(triggers) == {"workflow_dispatch"}

    dispatch = triggers["workflow_dispatch"]
    assert isinstance(dispatch, dict)
    inputs = dispatch["inputs"]
    assert isinstance(inputs, dict)
    assert set(inputs) == {
        "stage",
        "campaign_cycles",
        "max_orders_per_cycle",
        "confirm_practice_write",
    }
    stage = inputs["stage"]
    assert isinstance(stage, dict)
    assert stage["options"] == ["read-only", "round-trip", "campaign"]


def test_practice_validation_serializes_runs_and_defaults_to_shadow() -> None:
    workflow = _workflow()
    concurrency = workflow["concurrency"]
    assert isinstance(concurrency, dict)
    assert concurrency["cancel-in-progress"] == "false"

    job = workflow["jobs"]["practice-validation"]  # type: ignore[index]
    assert isinstance(job, dict)
    env = job["env"]
    assert isinstance(env, dict)
    assert env["FOREX_PROVIDER"] == "oanda"
    assert env["FOREX_MODE"] == "shadow"
    assert env["FOREX_ENABLE_PAPER_ORDERS"] == "false"
    assert env["FOREX_BUILD_REVISION"] == "${{ github.sha }}"


def test_practice_validation_contains_complete_gated_sequence() -> None:
    text = WORKFLOW.read_text(encoding="utf-8")
    assert "refs/heads/main" in text
    assert "confirm_practice_write=true" in text
    assert "python scripts/smoke_oanda.py" in text
    assert text.count("forex-trader sync") >= 2
    assert "--all-currency-pairs" in text
    assert "shadow-campaign.jsonl" in text
    assert "python scripts/oanda_round_trip.py" in text
    assert "--execute" in text
    assert "practice-campaign.jsonl" in text
    assert "python scripts/analyze_campaign.py" in text
    assert "forex-trader promotion" in text


def test_practice_validation_never_references_live_oanda_endpoint() -> None:
    text = WORKFLOW.read_text(encoding="utf-8")
    assert "api-fxtrade.oanda.com" not in text
    assert "stream-fxtrade.oanda.com" not in text
