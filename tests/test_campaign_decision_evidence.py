from __future__ import annotations

import json
from types import SimpleNamespace

from forex_trader.application.campaign import PracticeCampaignRunner
from forex_trader.domain.enums import DecisionDisposition, RiskDisposition


class DecisionEvidenceEngine:
    def __init__(self) -> None:
        self.calls = 0

    def evaluate(self, instrument: str, *, execute: bool = False):  # type: ignore[no-untyped-def]
        self.calls += 1
        if instrument == "GBP_USD":
            raise RuntimeError("provider unavailable")
        return SimpleNamespace(
            candidate=SimpleNamespace(
                disposition=DecisionDisposition.TRADE,
                rejection_code=None,
                setup_family="zone_liquidity_sweep_reclaim",
                setup_state="entry_confirmed",
                evidence={
                    "regime": "trend",
                    "selected_policy": "sweep_reclaim:v1",
                    "policy_authority": "practice",
                    "confirmation_categories": ["price", "fundamental"],
                    "confirmation_source_ids": ["price", "macro"],
                },
            ),
            risk=SimpleNamespace(disposition=RiskDisposition.GRANTED, reasons=("authorized",), units=1000),
            order=None,
            quote=None,
            metadata={"session_phase": "london"},
        )

    def promotion_status(self):  # type: ignore[no-untyped-def]
        return {"ready": False}


def test_campaign_writes_one_detailed_row_per_attempt_without_changing_cycle_aggregate(tmp_path) -> None:
    aggregate = tmp_path / "aggregate.jsonl"
    decisions = tmp_path / "decisions.jsonl"
    runner = PracticeCampaignRunner(
        DecisionEvidenceEngine(),  # type: ignore[arg-type]
        ["EUR_USD", "GBP_USD"],
        execute=False,
        evidence_path=aggregate,
        decision_evidence_path=decisions,
    )
    report = runner.run_cycle()
    rows = [json.loads(line) for line in decisions.read_text(encoding="utf-8").splitlines()]
    assert report.instruments_evaluated == 1
    assert report.errors == 1
    assert len(rows) == 2
    assert rows[0]["instrument"] == "EUR_USD"
    assert rows[0]["regime"] == "trend"
    assert rows[0]["session_phase"] == "london"
    assert rows[0]["execution_enabled"] is False
    assert rows[1]["instrument"] == "GBP_USD"
    assert rows[1]["error_type"] == "RuntimeError"
    assert "provider unavailable" in rows[1]["error_message"]
    aggregate_row = json.loads(aggregate.read_text(encoding="utf-8").strip())
    assert aggregate_row["instruments_evaluated"] == 1
    assert aggregate_row["errors"] == 1
