from __future__ import annotations

from fastapi.testclient import TestClient

from forex_trader.api.app import create_app


def test_liveness_stays_up_when_order_readiness_is_fail_closed(engine) -> None:  # type: ignore[no-untyped-def]
    client = TestClient(create_app(engine, allow_unsafe_local_mutations=True))
    assert client.get("/health/live").status_code == 200
    response = client.get("/health/ready?instrument=EUR_USD")
    assert response.status_code == 503
    detail = response.json()["detail"]
    assert detail["ready"] is False
    assert "RECONCILIATION_NOT_READY" in detail["reasons"]


def test_readiness_is_observable_without_enabling_broker_writes(engine) -> None:  # type: ignore[no-untyped-def]
    engine.enable_paper_orders = False
    client = TestClient(create_app(engine, allow_unsafe_local_mutations=True))
    ready = client.get("/health/ready?instrument=EUR_USD")
    assert ready.status_code == 200
    assert ready.json()["ready"] is True
    runtime = client.get("/v1/readiness/EUR_USD")
    assert runtime.status_code == 200
    assert runtime.json()["instrument"] == "EUR_USD"
    assert runtime.json()["ready"] is True
