from fastapi.testclient import TestClient

from forex_trader.api.app import create_app


def test_api_health_status_and_evaluation(engine) -> None:  # type: ignore[no-untyped-def]
    client = TestClient(create_app(engine))
    assert client.get("/health").json() == {"status": "ok"}
    status = client.get("/v1/status").json()
    assert status["mode"] == "paper"
    response = client.post("/v1/evaluate/EUR_USD?execute=true")
    assert response.status_code == 200
    assert response.json()["order"]["status"] == "filled"


def test_api_ingests_release_and_news(engine) -> None:  # type: ignore[no-untyped-def]
    client = TestClient(create_app(engine))
    release = client.post(
        "/v1/fundamentals/releases",
        json={
            "currency": "USD",
            "category": "labor",
            "actual": "250",
            "forecast": "200",
            "previous": "180",
            "higher_is_positive": True,
            "importance": "1",
        },
    )
    assert release.status_code == 200
    assert float(release.json()["labor"]) > 0
    news = client.post(
        "/v1/fundamentals/news",
        json={"currency": "EUR", "headline": "Growth strong and inflation higher"},
    )
    assert news.status_code == 200


def test_api_exposes_decision_history(engine) -> None:  # type: ignore[no-untyped-def]
    client = TestClient(create_app(engine))
    client.post("/v1/evaluate/EUR_USD")
    records = client.get("/v1/decisions?limit=1")
    assert records.status_code == 200
    assert len(records.json()) == 1
