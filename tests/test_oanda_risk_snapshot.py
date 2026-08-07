from __future__ import annotations

from decimal import Decimal

from forex_trader.adapters.oanda_optimized import OptimizedOandaPracticeClient
from forex_trader.adapters.oanda_safe import SafeOandaPracticeClient
from forex_trader.config import AppConfig, build_engine
from forex_trader.domain.enums import ProviderKind


def _account_payload() -> dict[str, object]:
    return {
        "account": {
            "id": "practice-001",
            "currency": "USD",
            "balance": "10000.00",
            "NAV": "10010.00",
            "marginUsed": "50.00",
            "marginAvailable": "9960.00",
            "unrealizedPL": "10.00",
            "openPositionCount": 1,
            "positions": [
                {
                    "instrument": "EUR_USD",
                    "long": {"units": "100", "averagePrice": "1.1000"},
                    "short": {"units": "-100", "averagePrice": "1.1010"},
                    "unrealizedPL": "2.50",
                },
                {
                    "instrument": "GBP_USD",
                    "long": {"units": "0"},
                    "short": {"units": "0"},
                    "unrealizedPL": "0",
                },
            ],
        }
    }


def test_risk_scope_reuses_positions_from_same_account_details_response(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    client = OptimizedOandaPracticeClient(token="token", account_id="practice-001")
    calls: list[str] = []

    def request(method: str, path: str, **kwargs):  # type: ignore[no-untyped-def]
        calls.append(path)
        if path == "/v3/accounts/practice-001":
            return _account_payload()
        raise AssertionError(f"unexpected request {path}")

    monkeypatch.setattr(client, "_request", request)
    monkeypatch.setattr(client, "realized_pl_today", lambda: Decimal("3.25"))

    with client.risk_read_scope():
        account = client.account_summary()
        positions = client.positions()

    assert calls == ["/v3/accounts/practice-001"]
    assert account.account_id == "practice-001"
    assert account.balance == Decimal("10000.00")
    assert account.realized_pl_today == Decimal("3.25")
    assert len(positions) == 1
    assert positions[0].instrument == "EUR_USD"
    # Gross hedged exposure must survive even when signed net units are zero.
    assert positions[0].long_units == Decimal("100")
    assert positions[0].short_units == Decimal("-100")
    assert positions[0].net_units == 0


def test_risk_scope_position_snapshot_is_one_shot(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    client = OptimizedOandaPracticeClient(token="token", account_id="practice-001")
    calls: list[str] = []

    def request(method: str, path: str, **kwargs):  # type: ignore[no-untyped-def]
        calls.append(path)
        if path == "/v3/accounts/practice-001":
            return _account_payload()
        if path == "/v3/accounts/practice-001/openPositions":
            return {"positions": []}
        raise AssertionError(f"unexpected request {path}")

    monkeypatch.setattr(client, "_request", request)
    monkeypatch.setattr(client, "realized_pl_today", lambda: Decimal("0"))

    with client.risk_read_scope():
        client.account_summary()
        assert len(client.positions()) == 1
        assert client.positions() == []

    assert calls == [
        "/v3/accounts/practice-001",
        "/v3/accounts/practice-001/openPositions",
    ]


def test_second_account_checkpoint_fetches_fresh_account_details(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    client = OptimizedOandaPracticeClient(token="token", account_id="practice-001")
    calls: list[str] = []

    def request(method: str, path: str, **kwargs):  # type: ignore[no-untyped-def]
        calls.append(path)
        assert path == "/v3/accounts/practice-001"
        payload = _account_payload()
        payload["account"]["NAV"] = "10010.00" if len(calls) == 1 else "9990.00"  # type: ignore[index]
        return payload

    monkeypatch.setattr(client, "_request", request)
    monkeypatch.setattr(client, "realized_pl_today", lambda: Decimal("0"))

    with client.risk_read_scope():
        first = client.account_summary()
        client.positions()
        second = client.account_summary()
        client.positions()

    assert calls == ["/v3/accounts/practice-001", "/v3/accounts/practice-001"]
    assert first.nav == Decimal("10010.00")
    assert second.nav == Decimal("9990.00")


def test_outside_risk_scope_inherited_summary_and_positions_remain_available(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    client = OptimizedOandaPracticeClient(token="token", account_id="practice-001")
    calls: list[str] = []

    def request(method: str, path: str, **kwargs):  # type: ignore[no-untyped-def]
        calls.append(path)
        if path == "/v3/accounts/practice-001/summary":
            return {
                "account": {
                    "id": "practice-001",
                    "currency": "USD",
                    "balance": "10000",
                    "NAV": "10000",
                    "marginUsed": "0",
                    "marginAvailable": "10000",
                    "unrealizedPL": "0",
                    "openPositionCount": 0,
                }
            }
        if path == "/v3/accounts/practice-001/openPositions":
            return {"positions": []}
        raise AssertionError(f"unexpected request {path}")

    monkeypatch.setattr(client, "_request", request)
    monkeypatch.setattr(client, "realized_pl_today", lambda: Decimal("0"))
    assert client.account_summary().balance == Decimal("10000")
    assert client.positions() == []
    assert calls == [
        "/v3/accounts/practice-001/summary",
        "/v3/accounts/practice-001/openPositions",
    ]


def test_nested_risk_scope_shares_one_pending_snapshot(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    client = OptimizedOandaPracticeClient(token="token", account_id="practice-001")
    calls: list[str] = []
    monkeypatch.setattr(
        client,
        "_request",
        lambda method, path, **kwargs: calls.append(path) or _account_payload(),
    )
    monkeypatch.setattr(client, "realized_pl_today", lambda: Decimal("0"))

    with client.risk_read_scope():
        client.account_summary()
        with client.risk_read_scope():
            positions = client.positions()
    assert len(positions) == 1
    assert calls == ["/v3/accounts/practice-001"]


def test_build_engine_uses_optimized_oanda_client(tmp_path) -> None:
    engine = build_engine(
        AppConfig(
            provider=ProviderKind.OANDA,
            database_path=str(tmp_path / "oanda.db"),
            oanda_token="token",
            oanda_account_id="practice-001",
        )
    )
    assert isinstance(engine.broker, OptimizedOandaPracticeClient)
    assert isinstance(engine.broker, SafeOandaPracticeClient)
