from datetime import UTC, datetime
from decimal import Decimal

import httpx
import pytest

from forex_trader.adapters.oanda import OandaApiError, OandaPracticeClient
from forex_trader.domain.enums import Direction, OrderStatus
from forex_trader.domain.models import OrderRequest


def instrument_response() -> dict[str, object]:
    return {
        "instruments": [
            {
                "name": "EUR_USD",
                "displayPrecision": 5,
                "pipLocation": -4,
                "tradeUnitsPrecision": 0,
                "minimumTradeSize": "1",
                "maximumOrderUnits": "100000000",
            }
        ]
    }


def test_oanda_reads_account_quote_candles_and_positions() -> None:
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
                        "marginAvailable": "9991.00",
                        "unrealizedPL": "1.00",
                        "openPositionCount": 1,
                    }
                },
            )
        if request.url.path == "/v3/accounts/A/transactions":
            return httpx.Response(
                200,
                json={
                    "pages": [
                        "https://api-fxpractice.oanda.com/v3/accounts/A/transactions/idrange?from=1&to=2"
                    ]
                },
            )
        if request.url.path == "/v3/accounts/A/transactions/idrange":
            return httpx.Response(
                200,
                json={
                    "transactions": [
                        {"pl": "-5", "financing": "-0.25", "commission": "-0.10"},
                        {"pl": "2", "financing": "0", "commission": "0"},
                    ]
                },
            )
        if request.url.path == "/v3/accounts/A/pricing":
            return httpx.Response(
                200,
                json={
                    "prices": [
                        {
                            "status": "tradeable",
                            "time": "2026-01-01T00:00:00Z",
                            "bids": [{"price": "1.1000"}],
                            "asks": [{"price": "1.1002"}],
                        }
                    ]
                },
            )
        if request.url.path == "/v3/accounts/A/instruments":
            return httpx.Response(200, json=instrument_response())
        if request.url.path == "/v3/accounts/A/openPositions":
            return httpx.Response(
                200,
                json={
                    "positions": [
                        {
                            "instrument": "EUR_USD",
                            "long": {"units": "100"},
                            "short": {"units": "0"},
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
    assert oanda.account().margin_available == Decimal("9991.00")
    assert oanda.account().realized_pl_today == Decimal("-3.35")
    assert oanda.quote("EUR_USD").spread == Decimal("0.0002")
    assert oanda.instrument_spec("EUR_USD").format_price(Decimal("1.1")) == "1.10000"
    assert oanda.has_open_position("EUR_USD") is True
    candles = oanda.candles("EUR_USD", "M5", 10)
    assert len(candles) == 1
    assert candles[0].time.tzinfo is not None


def test_oanda_market_order_payload_and_fill() -> None:
    captured: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/v3/accounts/A/instruments":
            return httpx.Response(200, json=instrument_response())
        if request.url.path == "/v3/accounts/A/orders":
            captured["body"] = request.read().decode()
            return httpx.Response(
                201,
                json={
                    "orderFillTransaction": {
                        "id": "12",
                        "orderID": "11",
                        "price": "1.1002",
                        "units": "100",
                        "tradeOpened": {"tradeID": "77"},
                    }
                },
            )
        raise AssertionError(request.url)

    client = httpx.Client(transport=httpx.MockTransport(handler))
    oanda = OandaPracticeClient(token="token", account_id="A", client=client)
    result = oanda.place_market_order(
        OrderRequest(
            "c-1",
            "EUR_USD",
            Direction.LONG,
            100,
            Decimal("1.09"),
            Decimal("1.12"),
            "signal-key",
        )
    )
    assert result.status is OrderStatus.FILLED
    assert result.fill_price == Decimal("1.1002")
    assert result.provider_trade_id == "77"
    assert '"stopLossOnFill"' in str(captured["body"])
    assert '"clientExtensions"' in str(captured["body"])
    assert '"price":"1.09000"' in str(captured["body"])
    assert "signal-key" in str(captured["body"])


def test_oanda_discovers_account_and_handles_rejection() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/v3/accounts":
            return httpx.Response(200, json={"accounts": [{"id": "DISCOVERED"}]})
        if request.url.path == "/v3/accounts/DISCOVERED/instruments":
            return httpx.Response(200, json=instrument_response())
        if request.url.path == "/v3/accounts/DISCOVERED/orders":
            return httpx.Response(400, text="bad order")
        raise AssertionError(request.url)

    client = httpx.Client(transport=httpx.MockTransport(handler))
    oanda = OandaPracticeClient(token="token", account_id=None, client=client)
    assert oanda.discover_account_id() == "DISCOVERED"
    with pytest.raises(OandaApiError, match="HTTP 400"):
        oanda.place_market_order(
            OrderRequest("c-2", "EUR_USD", Direction.LONG, 100, Decimal("1.09"), Decimal("1.12"))
        )


def test_oanda_order_rejection_response_is_mapped() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/v3/accounts/A/instruments":
            return httpx.Response(200, json=instrument_response())
        return httpx.Response(201, json={"orderRejectTransaction": {"id": "99"}})

    client = httpx.Client(transport=httpx.MockTransport(handler))
    oanda = OandaPracticeClient(token="token", account_id="A", client=client)
    result = oanda.place_market_order(
        OrderRequest("c-3", "EUR_USD", Direction.LONG, 100, Decimal("1.09"), Decimal("1.12"))
    )
    assert result.status is OrderStatus.REJECTED


def test_oanda_retries_transient_response_without_leaking_token() -> None:
    attempts = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            return httpx.Response(503, text="temporary")
        return httpx.Response(200, json={"accounts": [{"id": "A"}]})

    sleeps: list[float] = []
    client = httpx.Client(transport=httpx.MockTransport(handler))
    oanda = OandaPracticeClient(
        token="super-secret",
        account_id=None,
        client=client,
        max_retries=1,
        sleeper=sleeps.append,
    )
    assert oanda.discover_account_id() == "A"
    assert attempts == 2
    assert sleeps == [0.25]
    assert "super-secret" not in repr(oanda)


def test_oanda_can_close_opened_trade() -> None:
    captured: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["method"] = request.method
        captured["path"] = request.url.path
        captured["body"] = request.read().decode()
        return httpx.Response(200, json={"orderFillTransaction": {"id": "90"}})

    client = httpx.Client(transport=httpx.MockTransport(handler))
    oanda = OandaPracticeClient(token="token", account_id="A", client=client)
    payload = oanda.close_trade("77")
    assert payload["orderFillTransaction"]["id"] == "90"
    assert captured["method"] == "PUT"
    assert captured["path"] == "/v3/accounts/A/trades/77/close"
    assert '"ALL"' in str(captured["body"])


def test_oanda_rejects_foreign_transaction_page_url() -> None:
    client = httpx.Client(
        transport=httpx.MockTransport(
            lambda request: httpx.Response(200, json={"pages": ["https://evil.example/page"]})
        )
    )
    oanda = OandaPracticeClient(token="token", account_id="A", client=client)
    with pytest.raises(OandaApiError, match="practice host"):
        oanda.realized_pl_today()


def test_oanda_does_not_retry_unknown_market_order_outcome() -> None:
    attempts = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal attempts
        if request.url.path == "/v3/accounts/A/instruments":
            return httpx.Response(200, json=instrument_response())
        attempts += 1
        raise httpx.ConnectError("connection dropped", request=request)

    client = httpx.Client(transport=httpx.MockTransport(handler))
    oanda = OandaPracticeClient(
        token="token",
        account_id="A",
        client=client,
        max_retries=3,
        sleeper=lambda _: None,
    )
    result = oanda.place_market_order(
        OrderRequest(
            "c-unknown",
            "EUR_USD",
            Direction.LONG,
            100,
            Decimal("1.09"),
            Decimal("1.12"),
            "signal-unknown",
        )
    )
    assert attempts == 1
    assert result.status is OrderStatus.UNKNOWN
    assert "outcome is unknown" in result.raw["error"]


def test_oanda_positions_and_conversion_rate() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/v3/accounts/A/openPositions":
            return httpx.Response(
                200,
                json={
                    "positions": [
                        {
                            "instrument": "EUR_GBP",
                            "long": {"units": "1000", "averagePrice": "0.8500"},
                            "short": {"units": "0"},
                            "unrealizedPL": "3.5",
                        }
                    ]
                },
            )
        if request.url.path == "/v3/accounts/A/pricing":
            instrument = request.url.params["instruments"]
            if instrument == "GBP_USD":
                return httpx.Response(
                    200,
                    json={
                        "prices": [
                            {
                                "status": "tradeable",
                                "time": "2026-01-01T00:00:00Z",
                                "bids": [{"price": "1.2500"}],
                                "asks": [{"price": "1.2502"}],
                            }
                        ]
                    },
                )
            return httpx.Response(404, text="unsupported")
        raise AssertionError(request.url)

    client = httpx.Client(transport=httpx.MockTransport(handler))
    oanda = OandaPracticeClient(token="token", account_id="A", client=client)
    positions = oanda.positions()
    assert positions[0].net_units == Decimal("1000")
    assert positions[0].long_average_price == Decimal("0.8500")
    assert oanda.conversion_rate("GBP", "USD") == Decimal("1.2501")


def test_oanda_reconciles_filled_order_by_client_id() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/v3/accounts/A/orders/@ft-client":
            return httpx.Response(
                200,
                json={
                    "order": {
                        "id": "41",
                        "state": "FILLED",
                        "fillingTransactionID": "42",
                    }
                },
            )
        if request.url.path == "/v3/accounts/A/transactions/42":
            return httpx.Response(
                200,
                json={
                    "transaction": {
                        "id": "42",
                        "type": "ORDER_FILL",
                        "orderID": "41",
                        "instrument": "EUR_USD",
                        "units": "100",
                        "price": "1.1010",
                        "tradeOpened": {"tradeID": "77"},
                    }
                },
            )
        raise AssertionError(request.url)

    client = httpx.Client(transport=httpx.MockTransport(handler))
    oanda = OandaPracticeClient(token="token", account_id="A", client=client)
    result = oanda.reconcile_order(
        client_order_id="ft-client", instrument="EUR_USD", units=100
    )
    assert result is not None
    assert result.status is OrderStatus.FILLED
    assert result.fill_price == Decimal("1.1010")
    assert result.provider_trade_id == "77"


def test_oanda_reconcile_falls_back_to_transaction_history() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/v3/accounts/A/orders/@ft-client":
            return httpx.Response(404, text="not found")
        if request.url.path == "/v3/accounts/A/transactions":
            return httpx.Response(
                200,
                json={
                    "pages": [
                        "https://api-fxpractice.oanda.com/v3/accounts/A/transactions/idrange?from=50&to=51"
                    ]
                },
            )
        if request.url.path == "/v3/accounts/A/transactions/idrange":
            return httpx.Response(
                200,
                json={
                    "transactions": [
                        {
                            "id": "50",
                            "type": "MARKET_ORDER",
                            "clientExtensions": {"id": "ft-client", "tag": "forex-trader"},
                        },
                        {
                            "id": "51",
                            "type": "ORDER_FILL",
                            "orderID": "50",
                            "instrument": "EUR_USD",
                            "units": "-25",
                            "price": "1.0990",
                            "tradeOpened": {"tradeID": "90"},
                        },
                    ]
                },
            )
        raise AssertionError(request.url)

    client = httpx.Client(transport=httpx.MockTransport(handler))
    oanda = OandaPracticeClient(token="token", account_id="A", client=client)
    result = oanda.reconcile_order(
        client_order_id="ft-client", instrument="EUR_USD", units=-25
    )
    assert result is not None
    assert result.status is OrderStatus.FILLED
    assert result.units == -25


def test_oanda_transaction_stream_skips_heartbeats_by_default() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.host == "stream-fxpractice.oanda.com"
        return httpx.Response(
            200,
            content=(
                b'{"type":"HEARTBEAT","lastTransactionID":"10","time":"2026-01-01T00:00:00Z"}\n'
                b'{"id":"11","type":"ORDER_FILL","time":"2026-01-01T00:00:01Z"}\n'
            ),
        )

    client = httpx.Client(transport=httpx.MockTransport(handler))
    oanda = OandaPracticeClient(token="token", account_id="A", client=client)
    events = list(oanda.transaction_stream(max_events=1))
    assert events == [{"id": "11", "type": "ORDER_FILL", "time": "2026-01-01T00:00:01Z"}]


def test_oanda_transactions_since_and_last_transaction_id() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/v3/accounts/A/summary":
            return httpx.Response(200, json={"lastTransactionID": "10", "account": {}})
        if request.url.path == "/v3/accounts/A/transactions/sinceid":
            assert request.url.params["id"] == "10"
            return httpx.Response(
                200,
                json={"transactions": [{"id": "11", "type": "ORDER_FILL"}], "lastTransactionID": "11"},
            )
        raise AssertionError(request.url)

    client = httpx.Client(transport=httpx.MockTransport(handler))
    oanda = OandaPracticeClient(token="token", account_id="A", client=client)
    assert oanda.last_transaction_id() == "10"
    transactions, last_id = oanda.transactions_since("10")
    assert transactions[0]["id"] == "11"
    assert last_id == "11"


def test_oanda_candles_between_uses_bounded_time_windows() -> None:
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        assert "count" not in request.url.params
        if calls == 1:
            return httpx.Response(
                200,
                json={
                    "candles": [
                        {
                            "complete": True,
                            "time": "2026-01-01T00:00:00Z",
                            "volume": 10,
                            "mid": {"o": "1.1", "h": "1.2", "l": "1.0", "c": "1.1"},
                        },
                        {
                            "complete": True,
                            "time": "2026-01-01T00:05:00Z",
                            "volume": 10,
                            "mid": {"o": "1.1", "h": "1.2", "l": "1.0", "c": "1.11"},
                        },
                    ]
                },
            )
        return httpx.Response(200, json={"candles": []})

    client = httpx.Client(transport=httpx.MockTransport(handler))
    oanda = OandaPracticeClient(token="token", account_id="A", client=client)
    candles = oanda.candles_between(
        "EUR_USD",
        "M5",
        datetime(2026, 1, 1, tzinfo=UTC),
        datetime(2026, 1, 1, 0, 10, tzinfo=UTC),
    )
    assert [c.close for c in candles] == [Decimal("1.1"), Decimal("1.11")]


def test_oanda_reconcile_pending_and_cancelled_orders() -> None:
    state = {"value": "PENDING"}

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/v3/accounts/A/orders/@ft-pending":
            return httpx.Response(200, json={"order": {"id": "70", "state": state["value"]}})
        raise AssertionError(request.url)

    client = httpx.Client(transport=httpx.MockTransport(handler))
    oanda = OandaPracticeClient(token="token", account_id="A", client=client)
    pending = oanda.reconcile_order(client_order_id="ft-pending", instrument="EUR_USD", units=10)
    assert pending is not None and pending.status is OrderStatus.CREATED
    state["value"] = "CANCELLED"
    cancelled = oanda.reconcile_order(client_order_id="ft-pending", instrument="EUR_USD", units=10)
    assert cancelled is not None and cancelled.status is OrderStatus.REJECTED


def test_oanda_transaction_stream_can_include_heartbeat_and_detect_invalid_json() -> None:
    responses = [
        b'{"type":"HEARTBEAT","lastTransactionID":"10"}\n',
        b'not-json\n',
    ]

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=responses.pop(0))

    client = httpx.Client(transport=httpx.MockTransport(handler))
    oanda = OandaPracticeClient(token="token", account_id="A", client=client)
    heartbeat = list(oanda.transaction_stream(max_events=1, include_heartbeats=True))
    assert heartbeat[0]["type"] == "HEARTBEAT"
    with pytest.raises(OandaApiError, match="invalid JSON"):
        list(oanda.transaction_stream(max_events=1))


def test_oanda_last_transaction_id_requires_cursor() -> None:
    client = httpx.Client(
        transport=httpx.MockTransport(
            lambda request: httpx.Response(200, json={"account": {}})
        )
    )
    oanda = OandaPracticeClient(token="token", account_id="A", client=client)
    with pytest.raises(OandaApiError, match="lastTransactionID"):
        oanda.last_transaction_id()


def test_oanda_conversion_rate_can_use_inverse_and_return_none() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/v3/accounts/A/pricing":
            instrument = request.url.params["instruments"]
            if instrument == "USD_JPY":
                return httpx.Response(
                    200,
                    json={
                        "prices": [
                            {
                                "status": "tradeable",
                                "time": "2026-01-01T00:00:00Z",
                                "bids": [{"price": "150.00"}],
                                "asks": [{"price": "150.02"}],
                            }
                        ]
                    },
                )
            return httpx.Response(404, text="missing")
        raise AssertionError(request.url)

    client = httpx.Client(transport=httpx.MockTransport(handler))
    oanda = OandaPracticeClient(token="token", account_id="A", client=client)
    rate = oanda.conversion_rate("JPY", "USD")
    assert rate is not None and rate < Decimal("0.01")
    assert oanda.conversion_rate("XYZ", "ABC") is None


def test_oanda_candles_between_validates_range() -> None:
    client = httpx.Client(transport=httpx.MockTransport(lambda request: httpx.Response(200, json={})))
    oanda = OandaPracticeClient(token="token", account_id="A", client=client)
    now = datetime.now(UTC)
    with pytest.raises(ValueError, match="end must be after"):
        oanda.candles_between("EUR_USD", "M5", now, now)
    with pytest.raises(ValueError, match="maximum_pages"):
        oanda.candles_between("EUR_USD", "M5", now, now.replace(year=2027), maximum_pages=0)
    with pytest.raises(ValueError, match="unsupported candle"):
        oanda.candles_between("EUR_USD", "BAD", now, now.replace(year=2027))


def test_oanda_client_rejects_non_practice_hosts() -> None:
    import pytest

    with pytest.raises(ValueError, match="Practice REST"):
        OandaPracticeClient(
            token="token",
            account_id="A",
            rest_url="https://api-fxtrade.oanda.com",
        )
    with pytest.raises(ValueError, match="Practice stream"):
        OandaPracticeClient(
            token="token",
            account_id="A",
            stream_url="https://stream-fxtrade.oanda.com",
        )
