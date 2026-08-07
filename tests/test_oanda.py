from decimal import Decimal

import httpx

from forex_trader.adapters.oanda import OandaPracticeClient
from forex_trader.domain.enums import Direction, OrderStatus
from forex_trader.domain.models import OrderRequest


def test_oanda_reads_account_quote_and_candles() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/v3/accounts/A/summary":
            return httpx.Response(
                200,
                json={
                    "account": {
                        "id": "A",
                        "currency": "USD",
                        "balance": "10000.00",
                        "NAV": "10001.00",
                        "marginUsed": "10.00",
                        "unrealizedPL": "1.00",
                        "openPositionCount": 1,
                    }
                },
            )
        if request.url.path == "/v3/accounts/A/pricing":
            return httpx.Response(
                200,
                json={
                    "prices": [
                        {
                            "time": "2026-01-01T00:00:00Z",
                            "bids": [{"price": "1.1000"}],
                            "asks": [{"price": "1.1002"}],
                        }
                    ]
                },
            )
        if request.url.path == "/v3/instruments/EUR_USD/candles":
            return httpx.Response(
                200,
                json={
                    "candles": [
                        {
                            "complete": True,
                            "time": "2026-01-01T00:00:00Z",
                            "volume": 5,
                            "mid": {"o": "1.1", "h": "1.2", "l": "1.0", "c": "1.15"},
                        },
                        {
                            "complete": False,
                            "time": "2026-01-01T00:05:00Z",
                            "volume": 2,
                            "mid": {"o": "1.15", "h": "1.2", "l": "1.1", "c": "1.18"},
                        },
                    ]
                },
            )
        raise AssertionError(request.url)

    client = httpx.Client(transport=httpx.MockTransport(handler))
    oanda = OandaPracticeClient(token="token", account_id="A", client=client)
    assert oanda.account().balance == Decimal("10000.00")
    assert oanda.quote("EUR_USD").spread == Decimal("0.0002")
    candles = oanda.candles("EUR_USD", "M5", 10)
    assert len(candles) == 1
    assert candles[0].time.tzinfo is not None


def test_oanda_market_order_payload_and_fill() -> None:
    captured: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["body"] = request.read().decode()
        return httpx.Response(
            201,
            json={
                "orderFillTransaction": {
                    "id": "12",
                    "orderID": "11",
                    "price": "1.1002",
                    "units": "100",
                }
            },
        )

    client = httpx.Client(transport=httpx.MockTransport(handler))
    oanda = OandaPracticeClient(token="token", account_id="A", client=client)
    result = oanda.place_market_order(
        OrderRequest("c-1", "EUR_USD", Direction.LONG, 100, Decimal("1.09"), Decimal("1.12"))
    )
    assert result.status is OrderStatus.FILLED
    assert result.fill_price == Decimal("1.1002")
    assert '"stopLossOnFill"' in str(captured["body"])
    assert '"clientExtensions"' in str(captured["body"])


def test_oanda_discovers_account_and_handles_rejection() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/v3/accounts":
            return httpx.Response(200, json={"accounts": [{"id": "DISCOVERED"}]})
        if request.url.path == "/v3/accounts/DISCOVERED/orders":
            return httpx.Response(400, text="bad order")
        raise AssertionError(request.url)

    client = httpx.Client(transport=httpx.MockTransport(handler))
    oanda = OandaPracticeClient(token="token", account_id=None, client=client)
    assert oanda.discover_account_id() == "DISCOVERED"
    import pytest
    from forex_trader.adapters.oanda import OandaApiError

    with pytest.raises(OandaApiError, match="HTTP 400"):
        oanda.place_market_order(
            OrderRequest("c-2", "EUR_USD", Direction.LONG, 100, Decimal("1.09"), Decimal("1.12"))
        )


def test_oanda_order_rejection_response_is_mapped() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(201, json={"orderRejectTransaction": {"id": "99"}})

    client = httpx.Client(transport=httpx.MockTransport(handler))
    oanda = OandaPracticeClient(token="token", account_id="A", client=client)
    result = oanda.place_market_order(
        OrderRequest("c-3", "EUR_USD", Direction.LONG, 100, Decimal("1.09"), Decimal("1.12"))
    )
    assert result.status is OrderStatus.REJECTED
