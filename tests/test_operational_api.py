from __future__ import annotations

from fastapi.testclient import TestClient

from forex_trader.api.app import create_app
from forex_trader.config import AppConfig, build_engine


def test_operational_api_exposes_summary_events_and_metrics(tmp_path) -> None:  # type: ignore[no-untyped-def]
    engine = build_engine(AppConfig(database_path=str(tmp_path / "ops-api.db")))
    client = TestClient(create_app(engine, allow_unsafe_local_mutations=True))

    evaluation = client.post("/v1/evaluate/EUR_USD")
    assert evaluation.status_code == 200

    summary = client.get("/v1/operations/summary?hours=24")
    assert summary.status_code == 200
    payload = summary.json()
    assert payload["events_considered"] >= 1
    assert payload["event_counts"]["decision"] >= 1
    assert isinstance(payload["alerts"], list)

    events = client.get("/v1/operations/events?category=decision&limit=10")
    assert events.status_code == 200
    rows = events.json()
    assert rows
    assert all(row["category"] == "decision" for row in rows)

    metrics = client.get("/v1/operations/metrics")
    assert metrics.status_code == 200
    assert "text/plain" in metrics.headers["content-type"]
    assert "forex_operational_events_total" in metrics.text
    assert "forex_active_halts" in metrics.text


def test_operational_api_is_protected_and_rejects_invalid_filters(tmp_path) -> None:  # type: ignore[no-untyped-def]
    engine = build_engine(AppConfig(database_path=str(tmp_path / "ops-auth.db")))
    client = TestClient(create_app(engine, api_token="operator-token"))

    for path in (
        "/v1/operations/summary",
        "/v1/operations/events",
        "/v1/operations/metrics",
    ):
        assert client.get(path).status_code == 401
        assert client.get(path, headers={"Authorization": "Bearer operator-token"}).status_code == 200

    local = TestClient(create_app(engine, allow_unsafe_local_mutations=True))
    assert local.get("/v1/operations/summary?hours=0").status_code == 400
    assert local.get("/v1/operations/events?limit=0").status_code == 400
    assert local.get("/v1/operations/events?category=not-a-category").status_code == 400
    assert local.get("/v1/operations/events?severity=not-a-severity").status_code == 400
    assert local.get("/v1/operations/metrics?hours=721").status_code == 400
