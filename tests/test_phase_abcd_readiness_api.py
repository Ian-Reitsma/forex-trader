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
    assert detail["scope"] == "market_data_and_reconciliation"
    assert detail["requirements"]["fundamentals"] is False


def test_readiness_is_observable_without_enabling_broker_writes(engine) -> None:  # type: ignore[no-untyped-def]
    engine.enable_paper_orders = False
    client = TestClient(create_app(engine, allow_unsafe_local_mutations=True))
    ready = client.get("/health/ready?instrument=EUR_USD")
    assert ready.status_code == 200
    ready_payload = ready.json()
    assert ready_payload["ready"] is True
    assert ready_payload["scope"] == "market_data_and_reconciliation"
    assert ready_payload["requirements"]["calendar"] is False
    assert ready_payload["requirements"]["fundamentals"] is False
    assert ready_payload["requirements"]["institutional_flow"] is False
    assert isinstance(ready_payload["providers"], list)

    runtime = client.get("/v1/readiness/EUR_USD")
    assert runtime.status_code == 200
    payload = runtime.json()
    assert payload["instrument"] == "EUR_USD"
    assert payload["ready"] is True
    assert payload["eligibility_layers"]["final_trade_eligible"] is None
    assert payload["eligibility_layers"]["risk_breaker"]["endpoint"] == "/v1/risk/breaker"


def test_provider_and_breaker_observability_are_authenticated_control_routes(engine) -> None:  # type: ignore[no-untyped-def]
    client = TestClient(create_app(engine, api_token="operator-secret"))
    assert client.get("/v1/providers").status_code == 401
    assert client.get("/v1/risk/breaker").status_code == 401
    headers = {"Authorization": "Bearer operator-secret"}
    providers = client.get("/v1/providers", headers=headers)
    breaker = client.get("/v1/risk/breaker", headers=headers)
    assert providers.status_code == 200
    assert providers.json()["schema"] == "provider-capability-snapshot-v1"
    assert breaker.status_code == 200
    assert "supported" in breaker.json()
