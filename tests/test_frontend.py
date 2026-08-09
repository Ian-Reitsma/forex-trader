from pathlib import Path

from fastapi.testclient import TestClient

from forex_trader.api.app import create_app


def local_client(engine):  # type: ignore[no-untyped-def]
    return TestClient(create_app(engine, allow_unsafe_local_mutations=True))


def test_trading_cockpit_routes_and_assets_are_served(engine) -> None:  # type: ignore[no-untyped-def]
    client = local_client(engine)

    desk = client.get("/")
    assert desk.status_code == 200
    assert "Vector // FX Command" in desk.text
    assert "Current open positions" in desk.text
    assert "Backtesting laboratory" in desk.text

    news = client.get("/news")
    assert news.status_code == 200
    assert "News Intelligence" in news.text

    css = client.get("/assets/styles.css")
    javascript = client.get("/assets/app.js")
    assert css.status_code == 200
    assert javascript.status_code == 200
    assert "DECISION PRISM" not in javascript.text  # markup belongs to the shell, not duplicated in JS
    assert "embed-widget-advanced-chart.js" in javascript.text


def test_dashboard_read_models_are_real_engine_data(engine) -> None:  # type: ignore[no-untyped-def]
    client = local_client(engine)

    account = client.get("/v1/account")
    assert account.status_code == 200
    assert account.json()["account_id"]

    positions = client.get("/v1/positions")
    assert positions.status_code == 200
    assert isinstance(positions.json(), list)

    quote = client.get("/v1/market/EUR_USD/quote")
    assert quote.status_code == 200
    assert quote.json()["instrument"] == "EUR_USD"

    candles = client.get("/v1/market/EUR_USD/candles?granularity=M5&count=20")
    assert candles.status_code == 200
    assert len(candles.json()) == 20

    fundamentals = client.get("/v1/fundamentals/snapshots")
    assert fundamentals.status_code == 200
    assert isinstance(fundamentals.json(), list)

    scheduled = client.get("/v1/events/scheduled")
    assert scheduled.status_code == 200
    assert scheduled.json() == []


def test_frontend_assets_are_inside_the_python_package() -> None:
    frontend = Path(__file__).resolve().parents[1] / "src" / "forex_trader" / "frontend"
    assert (frontend / "index.html").is_file()
    assert (frontend / "styles.css").is_file()
    assert (frontend / "app.js").is_file()

    script = (frontend / "app.js").read_text(encoding="utf-8")
    assert "sessionStorage.setItem('forexApiToken'" in script
    assert "localStorage" not in script
    assert "fetch(`${apiBase()}${path}`" in script
    assert "/v1/positions" in script
    assert "/v1/decisions?limit=100" in script
