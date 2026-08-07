from datetime import UTC, datetime, timedelta
from decimal import Decimal

import httpx
import pytest

from forex_trader.adapters.oanda import OandaApiError
from forex_trader.adapters.oanda_safe import SafeOandaPracticeClient, _broker_time
from forex_trader.domain.enums import Direction, OrderStatus
from forex_trader.domain.models import OrderRequest


def instrument_response(**changes: object) -> dict[str, object]:
    item: dict[str, object] = {
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
    item.update(changes)
    return {"instruments": [item]}


def request(**changes: object) -> OrderRequest:
    values: dict[str, object] = {
        "client_order_id": "ft-safe",
        "instrument": "EUR_USD",
        "direction": Direction.LONG,
        "units": 100,
        "stop_loss": Decimal("1.0980"),
        "take_profit": Decimal("1.1040"),
        "execution_key": "signal-safe",
        "intended_price": Decimal("1.1002"),
        "price_bound": Decimal("1.1007"),
        "authorization_id": "risk-1",
    }
    values.update(changes)
    return OrderRequest(**values)  # type: ignore[arg-type]


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


def test_safe_oanda_transport_failure_is_ambiguous_not_retried() -> None:
    def handler(http_request: httpx.Request) -> httpx.Response:
        if http_request.url.path == "/v3/accounts/A/instruments":
            return httpx.Response(200, json=instrument_response())
        raise httpx.ReadTimeout("outcome unknown", request=http_request)

    client = httpx.Client(transport=httpx.MockTransport(handler))
    oanda = SafeOandaPracticeClient(token="token", account_id="A", client=client)
    result = oanda.place_market_order(request())
    assert result.status is OrderStatus.UNKNOWN
    assert "ReadTimeout" in str(result.raw["error"])


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


def test_safe_oanda_classifies_plain_4xx_and_missing_fill() -> None:
    responses = [
        httpx.Response(400, json={"errorCode": "ORDER_REJECTED", "errorMessage": "bad order"}),
        httpx.Response(201, json={"orderCreateTransaction": {"id": "10"}}),
    ]

    def handler(http_request: httpx.Request) -> httpx.Response:
        if http_request.url.path == "/v3/accounts/A/instruments":
            return httpx.Response(200, json=instrument_response())
        return responses.pop(0)

    client = httpx.Client(transport=httpx.MockTransport(handler))
    oanda = SafeOandaPracticeClient(token="token", account_id="A", client=client)
    rejected = oanda.place_market_order(request(client_order_id="plain-4xx"))
    unknown = oanda.place_market_order(request(client_order_id="missing-fill"))
    assert rejected.status is OrderStatus.REJECTED
    assert unknown.status is OrderStatus.UNKNOWN


def test_safe_oanda_enforces_broker_size_metadata() -> None:
    cases = [
        ({"minimumTradeSize": "10"}, 1, "minimum"),
        ({"maximumOrderUnits": "50", "maximumPositionSize": "0"}, 100, "broker maximum"),
        ({"maximumOrderUnits": "1000", "maximumPositionSize": "50"}, 100, "position maximum"),
    ]
    for metadata, units, message in cases:
        client = httpx.Client(
            transport=httpx.MockTransport(
                lambda http_request, metadata=metadata: httpx.Response(
                    200, json=instrument_response(**metadata)
                )
            )
        )
        oanda = SafeOandaPracticeClient(token="token", account_id="A", client=client)
        with pytest.raises(OandaApiError, match=message):
            oanda.place_market_order(request(units=units))


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
    top = oanda.quote("EUR_USD")
    assert top.bid == Decimal("1.1000")
    assert top.ask == Decimal("1.1002")


def test_safe_oanda_quote_fails_closed_for_bad_pricing_state() -> None:
    payloads = [
        {"prices": []},
        {
            "prices": [
                {
                    "status": "non-tradeable",
                    "time": "2026-08-07T13:00:00Z",
                    "bids": [{"price": "1.1", "liquidity": "10"}],
                    "asks": [{"price": "1.2", "liquidity": "10"}],
                }
            ]
        },
        {
            "prices": [
                {
                    "status": "tradeable",
                    "time": "2026-08-07T13:00:00Z",
                    "bids": [],
                    "asks": [{"price": "1.2", "liquidity": "10"}],
                }
            ]
        },
    ]
    messages = ["no price", "not tradeable", "no executable"]
    for payload, message in zip(payloads, messages, strict=True):
        client = httpx.Client(
            transport=httpx.MockTransport(lambda http_request, payload=payload: httpx.Response(200, json=payload))
        )
        oanda = SafeOandaPracticeClient(token="token", account_id="A", client=client)
        with pytest.raises(OandaApiError, match=message):
            oanda.quote("EUR_USD")


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
    with pytest.raises(RuntimeError, match="below requested units"):
        oanda.quote_for_units("EUR_USD", 100)


def test_safe_oanda_metadata_cache_and_currency_universe() -> None:
    calls = 0

    def handler(http_request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        if http_request.url.params.get("instruments"):
            return httpx.Response(200, json=instrument_response())
        return httpx.Response(
            200,
            json={
                "instruments": [
                    instrument_response(name="USD_JPY", displayPrecision=3, pipLocation=-2)["instruments"][0],
                    instrument_response(name="EUR_USD")["instruments"][0],
                    {"name": "XAU_USD", "type": "METAL", "displayPrecision": 2, "pipLocation": -1},
                ]
            },
        )

    client = httpx.Client(transport=httpx.MockTransport(handler))
    oanda = SafeOandaPracticeClient(token="token", account_id="A", client=client)
    first = oanda.instrument_spec("eur_usd")
    second = oanda.instrument_spec("EUR_USD")
    assert first is second
    assert calls == 1
    universe = oanda.currency_instruments()
    assert [spec.name for spec in universe] == ["EUR_USD", "USD_JPY"]
    assert universe[1].pip_size == Decimal("0.01")


def test_safe_oanda_missing_instrument_metadata_fails_closed() -> None:
    client = httpx.Client(
        transport=httpx.MockTransport(lambda http_request: httpx.Response(200, json={"instruments": []}))
    )
    oanda = SafeOandaPracticeClient(token="token", account_id="A", client=client)
    with pytest.raises(OandaApiError, match="metadata was not returned"):
        oanda.instrument_spec("EUR_USD")


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
    assert oanda.ensure_trade_protection("77", stop_loss=Decimal("1.098"), take_profit=Decimal("1.104")) is True


def test_safe_oanda_protection_validation_rejects_incomplete_trade_state() -> None:
    states = [
        {"trade": "bad"},
        {"trade": {"instrument": "EUR_USD"}},
        {
            "trade": {
                "instrument": "",
                "stopLossOrder": {"state": "PENDING", "price": "1.098"},
                "takeProfitOrder": {"state": "PENDING", "price": "1.104"},
            }
        },
    ]
    for payload in states:
        client = httpx.Client(
            transport=httpx.MockTransport(lambda http_request, payload=payload: httpx.Response(200, json=payload))
        )
        oanda = SafeOandaPracticeClient(token="token", account_id="A", client=client)
        assert oanda.verify_trade_protection("77", stop_loss=Decimal("1.098"), take_profit=Decimal("1.104")) is False


def test_safe_oanda_repairs_missing_protection_then_verifies() -> None:
    trade_reads = 0

    def handler(http_request: httpx.Request) -> httpx.Response:
        nonlocal trade_reads
        if http_request.url.path == "/v3/accounts/A/trades/77":
            trade_reads += 1
            if trade_reads <= 2:
                return httpx.Response(200, json={"trade": {"instrument": "EUR_USD"}})
            return httpx.Response(
                200,
                json={
                    "trade": {
                        "instrument": "EUR_USD",
                        "stopLossOrder": {"state": "PENDING", "price": "1.09800"},
                        "takeProfitOrder": {"state": "PENDING", "price": "1.10400"},
                    }
                },
            )
        if http_request.url.path == "/v3/accounts/A/instruments":
            return httpx.Response(200, json=instrument_response())
        if http_request.url.path == "/v3/accounts/A/trades/77/orders":
            return httpx.Response(200, json={"stopLossOrderTransaction": {"id": "20"}, "takeProfitOrderTransaction": {"id": "21"}})
        raise AssertionError(http_request.url)

    client = httpx.Client(transport=httpx.MockTransport(handler))
    oanda = SafeOandaPracticeClient(token="token", account_id="A", client=client)
    assert oanda.ensure_trade_protection("77", stop_loss=Decimal("1.098"), take_profit=Decimal("1.104")) is True


def test_safe_oanda_protection_repair_reject_or_ambiguity_fails_closed() -> None:
    for repair_response in (
        httpx.Response(400, json={"stopLossOrderRejectTransaction": {"id": "22"}}),
        httpx.Response(503, text="ambiguous"),
    ):
        def handler(http_request: httpx.Request, repair_response=repair_response) -> httpx.Response:
            if http_request.url.path == "/v3/accounts/A/trades/77":
                return httpx.Response(200, json={"trade": {"instrument": "EUR_USD"}})
            if http_request.url.path == "/v3/accounts/A/instruments":
                return httpx.Response(200, json=instrument_response())
            if http_request.url.path == "/v3/accounts/A/trades/77/orders":
                return repair_response
            raise AssertionError(http_request.url)

        client = httpx.Client(transport=httpx.MockTransport(handler))
        oanda = SafeOandaPracticeClient(token="token", account_id="A", client=client)
        assert oanda.ensure_trade_protection("77", stop_loss=Decimal("1.098"), take_profit=Decimal("1.104")) is False


def test_safe_oanda_transactions_between_validates_and_follows_pages() -> None:
    start = datetime(2025, 1, 1, tzinfo=UTC)
    end = start + timedelta(days=365)
    page_calls: list[str] = []

    def handler(http_request: httpx.Request) -> httpx.Response:
        if http_request.url.path == "/v3/accounts/A/transactions":
            marker = http_request.url.params.get("from", "")
            page = f"https://api-fxpractice.oanda.com/v3/accounts/A/transactions/page?from={marker}"
            return httpx.Response(200, json={"pages": [page]})
        if http_request.url.path == "/v3/accounts/A/transactions/page":
            page_calls.append(str(http_request.url))
            return httpx.Response(200, json={"transactions": [{"id": str(len(page_calls))}, "ignore-me"]})
        raise AssertionError(http_request.url)

    client = httpx.Client(transport=httpx.MockTransport(handler))
    oanda = SafeOandaPracticeClient(token="token", account_id="A", client=client)
    rows = oanda.transactions_between(start, end)
    assert [row["id"] for row in rows] == ["1", "2"]
    assert len(page_calls) == 2
    with pytest.raises(ValueError, match="range"):
        oanda.transactions_between(datetime(2026, 1, 1), end)
    with pytest.raises(ValueError, match="range"):
        oanda.transactions_between(end, start)


def test_safe_oanda_trade_instrument_and_json_edge_cases() -> None:
    responses = {
        "/v3/accounts/A/trades/77": httpx.Response(200, json={"trade": {}}),
        "/bad-json": httpx.Response(418, text="not-json"),
    }

    def handler(http_request: httpx.Request) -> httpx.Response:
        return responses[http_request.url.path]

    client = httpx.Client(transport=httpx.MockTransport(handler))
    oanda = SafeOandaPracticeClient(token="token", account_id="A", client=client)
    with pytest.raises(OandaApiError, match="did not expose"):
        oanda._trade_instrument("77")
    payload, status, ambiguous = oanda._write_json("POST", "/bad-json")
    assert status == 418
    assert ambiguous is False
    assert payload["errorMessage"] == "not-json"
    assert _broker_time({}) is None
    assert _broker_time({"time": "not-a-time"}) is None


def test_safe_oanda_requires_explicit_account_id_for_writes() -> None:
    client = httpx.Client(transport=httpx.MockTransport(lambda request: httpx.Response(200, json={})))
    oanda = SafeOandaPracticeClient(token="token", account_id=None, client=client)
    with pytest.raises(RuntimeError, match="ACCOUNT_ID"):
        oanda.place_market_order(request())
