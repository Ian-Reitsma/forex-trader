from __future__ import annotations

import httpx

from forex_trader.adapters.oanda_safe import SafeOandaPracticeClient
from forex_trader.application.sync import BrokerStateSynchronizer
from forex_trader.config import AppConfig
from forex_trader.domain.enums import OperatingMode, ProviderKind
from forex_trader.infrastructure.trading_repository import TradingRepository


def test_shadow_oanda_config_allows_token_only_account_discovery(tmp_path) -> None:
    config = AppConfig(
        provider=ProviderKind.OANDA,
        mode=OperatingMode.SHADOW,
        database_path=str(tmp_path / "readonly.db"),
        oanda_token="token",
        oanda_account_id=None,
        enable_paper_orders=False,
    )
    assert config.validate() == []


def test_token_only_client_discovers_account_and_synchronizes_transactions(tmp_path) -> None:
    paths: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        paths.append(request.url.path)
        if request.url.path == "/v3/accounts":
            return httpx.Response(200, json={"accounts": [{"id": "DISCOVERED"}]})
        if request.url.path == "/v3/accounts/DISCOVERED/summary":
            return httpx.Response(200, json={"lastTransactionID": "10"})
        if request.url.path == "/v3/accounts/DISCOVERED/transactions":
            return httpx.Response(200, json={"pages": []})
        if request.url.path == "/v3/accounts/DISCOVERED/transactions/sinceid":
            assert request.url.params.get("id") == "10"
            return httpx.Response(
                200,
                json={
                    "transactions": [
                        {
                            "id": "11",
                            "type": "DAILY_FINANCING",
                            "time": "2026-08-07T18:00:00Z",
                        }
                    ],
                    "lastTransactionID": "11",
                },
            )
        raise AssertionError(request.url)

    http = httpx.Client(transport=httpx.MockTransport(handler))
    client = SafeOandaPracticeClient(
        token="token",
        account_id=None,
        client=http,
    )
    repository = TradingRepository(str(tmp_path / "sync.db"))
    synchronizer = BrokerStateSynchronizer(client, repository, initial_history_days=1)

    assert synchronizer.catch_up() == 1
    assert client.account_id == "DISCOVERED"
    assert repository.get_broker_cursor("oanda.transactions") == "11"
    assert paths[0] == "/v3/accounts"
    assert paths.count("/v3/accounts") == 1
    assert "/v3/accounts/DISCOVERED/summary" in paths
    assert "/v3/accounts/DISCOVERED/transactions/sinceid" in paths


def test_enabling_oanda_writes_without_explicit_account_id_fails_validation(tmp_path) -> None:
    config = AppConfig(
        provider=ProviderKind.OANDA,
        mode=OperatingMode.PAPER,
        database_path=str(tmp_path / "write.db"),
        oanda_token="token",
        oanda_account_id=None,
        enable_paper_orders=True,
    )
    errors = config.validate()
    assert "OANDA_ACCOUNT_ID is required when paper broker writes are enabled" in errors
