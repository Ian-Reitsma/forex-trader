from decimal import Decimal

import httpx

from forex_trader.adapters.oanda_safe import SafeOandaPracticeClient
from forex_trader.domain.enums import Direction, OrderStatus
from forex_trader.domain.models import OrderRequest


def instrument_response() -> dict[str, object]:
    return {
        "instruments": [
            {
                "name": "EUR_USD",
                "type": "CURRENCY",
                "displayPrecision": 5,
                "pipLocation": -4,
                "tradeUnitsPrecision": 0,
                "minimumTradeSize": "1",
                "maximumOrderUnits": "1000000",
                "maximumPositionSize": "2000000",
                "marginRate": "0.02",
            }
        ]
    }


def request() -> OrderRequest:
    return OrderRequest(
        client_order_id="ft-safe",
        instrument="EUR_USD",
        direction=Direction.LONG,
        units=100,
        stop_loss=Decimal("1.0980"),
        take_profit=Decimal("1.1040"),
        execution_key="signal-safe",
        intended_price=Decimal("1.1002"),
        price_bound=Decimal("1.1007"),
        authorization_id="risk-1",
    )


def test_safe_oanda_maps_http_400_reject_transaction() -> None:
    def handler(http_request: httpx.Request) -> httpx.Response:
        if http_request.url.path == "/v3/accounts/A/instruments":
            return httpx.Response(200, json=instrument_response())
        if http_request.url.path == "/v3/accounts/A/orders":
            return httpx.Response(
                400,
                json={
                    "errorCode": "STOP_LOSS_ON_FILL_PRICE_INVALID",
                    "orderRejectTransaction": {
                        "id": "99",
                        "type": "MARKET_ORDER_REJECT",
                        "time": "2026-08-07T13:00:00Z",
                    },
                },
            )
        raise AssertionError(http_request.url)

    client = httpx.Client(transport=httpx.MockTransport(handler))
    oanda = SafeOandaPracticeClient(token="token", account_id="A", client=client)
    result = oanda.place_market_order(request())
    assert result.status is OrderStatus.REJECTED
    assert result.provider_order_id == "99"
    assert result.broker_time is not None


def test_safe_oanda_preserves_transient_write_as_unknown() -> None:
    def handler(http_request: httpx.Request) -> httpx.Response:
        if http_request.url.path == "/v3/accounts/A/instruments":
            return httpx.Response(200, json=instrument_response())
        return httpx.Response(503, text="temporary")

    client = httpx.Client(transport=httpx.MockTransport(handler))
    oanda = SafeOandaPracticeClient(token="token", account_id="A", client=client)
    result = oanda.place_market_order(request())
    assert result.status is OrderStatus.UNKNOWN
    assert "outcome unknown" in result.raw["error"]


def test_safe_oanda_adds_price_bound_and_reads_fill() -> None:
    captured: dict[str, str] = {}

    def handler(http_request: httpx.Request) -> httpx.Response:
        if http_request.url.path == "/v3/accounts/A/instruments":
            return httpx.Response(200, json=instrument_response())
        if http_request.url.path == "/v3/accounts/A/orders":
            captured["body"] = http_request.read().decode()
            return httpx.Response(
                201,
                json={
                    "orderFillTransaction": {
                        "id": "12",
                        "orderID": "11",
                        "instrument": "EUR_USD",
                        "time": "2026-08-07T13:00:00Z",
                        "price": "1.1003",
                        "units": "100",
                        "tradeOpened": {"tradeID": "77"},
                    }
                },
            )
        raise AssertionError(http_request.url)

    client = httpx.Client(transport=httpx.MockTransport(handler))
    oanda = SafeOandaPracticeClient(token="token", account_id="A", client=client)
    result = oanda.place_market_order(request())
    assert result.status is OrderStatus.FILLED
    assert result.provider_trade_id == "77"
    assert '"priceBound":"1.10070"' in captured["body"]
    assert "tradeClientExtensions" not in captured["body"]


def test_safe_oanda_quote_is_size_aware_across_price_buckets() -> None:
    def handler(http_request: httpx.Request) -> httpx.Response:
        assert http_request.url.path == "/v3/accounts/A/pricing"
        return httpx.Response(
            200,
            json={
                "prices": [
                    {
                        "status": "tradeable",
                        "time": "2026-08-07T13:00:00Z",
                        "bids": [
                            {"price": "1.1000", "liquidity": "50"},
                            {"price": "1.0999", "liquidity": "100"},
                        ],
                        "asks": [
                            {"price": "1.1002", "liquidity": "50"},
                            {"price": "1.1003", "liquidity": "100"},
                        ],
                    }
                ]
            },
        )

    client = httpx.Client(transport=httpx.MockTransport(handler))
    oanda = SafeOandaPracticeClient(token="token", account_id="A", client=client)
    quote = oanda.quote_for_units("EUR_USD", 100)
    assert quote.bid == Decimal("1.0999")
    assert quote.ask == Decimal("1.1003")
    assert quote.bid_liquidity == Decimal("150")
    assert quote.ask_liquidity == Decimal("150")


def test_safe_oanda_rejects_order_larger_than_available_price_buckets() -> None:
    def handler(http_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "prices": [
                    {
                        "status": "tradeable",
                        "time": "2026-08-07T13:00:00Z",
                        "bids": [{"price": "1.1000", "liquidity": "50"}],
                        "asks": [{"price": "1.1002", "liquidity": "50"}],
                    }
                ]
            },
        )

    client = httpx.Client(transport=httpx.MockTransport(handler))
    oanda = SafeOandaPracticeClient(token="token", account_id="A", client=client)
    import pytest

    with pytest.raises(RuntimeError, match="below requested units"):
        oanda.quote_for_units("EUR_USD", 100)


def test_safe_oanda_verifies_dependent_protection() -> None:
    def handler(http_request: httpx.Request) -> httpx.Response:
        if http_request.url.path == "/v3/accounts/A/trades/77":
            return httpx.Response(
                200,
                json={
                    "trade": {
                        "id": "77",
                        "instrument": "EUR_USD",
                        "stopLossOrder": {"state": "PENDING", "price": "1.09800"},
                        "takeProfitOrder": {"state": "PENDING", "price": "1.10400"},
                    }
                },
            )
        if http_request.url.path == "/v3/accounts/A/instruments":
            return httpx.Response(200, json=instrument_response())
        raise AssertionError(http_request.url)

    client = httpx.Client(transport=httpx.MockTransport(handler))
    oanda = SafeOandaPracticeClient(token="token", account_id="A", client=client)
    assert oanda.verify_trade_protection("77", stop_loss=Decimal("1.098"), take_profit=Decimal("1.104")) is True


def test_safe_oanda_requires_explicit_account_id_for_writes() -> None:
    client = httpx.Client(transport=httpx.MockTransport(lambda request: httpx.Response(200, json={})))
    oanda = SafeOandaPracticeClient(token="token", account_id=None, client=client)
    import pytest

    with pytest.raises(RuntimeError, match="ACCOUNT_ID"):
        oanda.place_market_order(request())
