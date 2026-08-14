from __future__ import annotations

import json

from forex_trader.application.campaign import PracticeCampaignRunner
from forex_trader.config import AppConfig, build_engine


def test_campaign_records_actionable_ablation_failure_details(tmp_path, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    engine = build_engine(AppConfig(database_path=str(tmp_path / "capture.db")))
    evidence = tmp_path / "campaign.jsonl"
    runner = PracticeCampaignRunner(
        engine,
        ["EUR_USD"],
        execute=False,
        evidence_path=evidence,
        ablation_evidence_path=tmp_path / "ablations.jsonl",
    )

    def fail_capture(**kwargs):  # type: ignore[no-untyped-def]
        assert kwargs["instrument"] == "EUR_USD"
        raise ValueError("full replay differs from production trace")

    monkeypatch.setattr(runner, "_capture_ablations", fail_capture)
    report = runner.run_cycle(7)

    assert report.ablation_errors == 1
    assert report.ablation_error_types == {"ValueError": 1}
    assert len(report.ablation_error_details) == 1
    detail = report.ablation_error_details[0]
    assert detail["cycle"] == 7
    assert detail["instrument"] == "EUR_USD"
    assert str(detail["snapshot_id"]).startswith("ab-")
    assert detail["variant"] is None
    assert detail["error_type"] == "ValueError"
    assert detail["error_message"] == "full replay differs from production trace"

    payload = json.loads(evidence.read_text(encoding="utf-8").strip())
    assert payload["ablation_error_details"] == [detail]
