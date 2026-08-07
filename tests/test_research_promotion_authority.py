from __future__ import annotations

import json
from pathlib import Path


def test_research_promotion_release_does_not_expand_practice_authority() -> None:
    policy_path = Path(__file__).resolve().parents[1] / "config" / "system-policy-v0.7.json"
    payload = json.loads(policy_path.read_text(encoding="utf-8"))
    strategies = {
        f"{item['name']}:{item['version']}": item["authority"]
        for item in payload["strategy_policies"]
    }

    assert payload["execution_boundary"]["live_money_enabled"] is False
    assert strategies["sweep_reclaim:v1"] == "practice"
    assert strategies["zone_continuation:v1"] == "shadow"
    assert strategies["breakout_retest:v1"] == "shadow"
    assert strategies["post_news_continuation:v1"] == "shadow"
    assert strategies["post_news_failure:v1"] == "research"
    assert [name for name, authority in strategies.items() if authority == "practice"] == ["sweep_reclaim:v1"]
