from __future__ import annotations

import time
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Any, Callable

import httpx

from forex_trader.domain.enums import OrderStatus
from forex_trader.domain.models import (
    AccountSnapshot,
    Candle,
    InstrumentSpec,
    OrderRequest,
    OrderResult,
    Quote,
)


class OandaApiError(RuntimeError):
    pass


class OandaOrderStateUnknown(OandaApiError):
    """The request may have reached OANDA, so it must not be submitted again blindly."""


class OandaPracticeClient:
    """Minimal OANDA REST-v20 practice adapter.

    The access token is installed only in the private HTTP client's authorization header.
    It is not retained as a public attribute, logged, serialized, or included in exceptions.
    """

    def __init__(
        self,
        *,
        token: str,
        account_id: str | None,
        rest_url: str = "https://api-fxpractice.oanda.com",
        timeout_seconds: float = 10.0,
        max_retries: int = 2,
        client: httpx.Client | None = None,
        sleeper: Callable[[float], None] = time.sleep,
    ) -> None:
        if not token:
            raise ValueError("OANDA token is required")
        if max_retries < 0:
            raise ValueError("max_retries must be non-negative")
        self.account_id = account_id
        self.rest_url = rest_url.rstrip("/")
        self.max_retries = max_retries
        self._sleeper = sleeper
        self._owns_client = client is None
        self.client = client or httpx.Client(
            timeout=timeout_seconds,
            headers={
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json",
                "Accept-Datetime-Format": "RFC3339",
                "User-Agent": "forex-trader/0.2",
            },
        )
        self._instrument_specs: dict[str, InstrumentSpec] = {}
        self._daily_pl_cache: tuple[date, float, Decimal] | None = None

    def close(self) -> None:
        if self._owns_client:
            self.client.close()

    def __enter__(self) -> "OandaPracticeClient":
        return self

    def __exit__(self, exc_type: object, exc: object, traceback: object) -> None:
        self.close()

    def discover_account_id(self) -> str:
        payload = self._request("GET", "/v3/accounts")
        accounts = sorted(payload.get("accounts", []), key=lambda item: str(item.get("id", "")))
        if not accounts:
            raise OandaApiError("the token does not expose any accounts")
        self.account_id = str(accounts[0]["id"])
        return self.account_id

    def _account_id(self) -> str:
        return self.account_id or self.discover_account_id()

    def instrument_spec(self, instrument: str) -> InstrumentSpec:
        instrument = instrument.upper()
        cached = self._instrument_specs.get(instrument)
        if cached is not None:
            return cached
        payload = self._request(
            "GET",
            f"/v3/accounts/{self._account_id()}/instruments",
            params={"instruments": instrument},
        )
        instruments = payload.get("instruments", [])
        if not instruments:
            raise OandaApiError(f"instrument metadata was not returned for {instrument}")
        item = instruments[0]
        maximum = item.get("maximumOrderUnits")
        spec = InstrumentSpec(
            name=str(item["name"]),
            display_precision=int(item["displayPrecision"]),
            pip_location=int(item["pipLocation"]),
            trade_units_precision=int(item.get("tradeUnitsPrecision", 0)),
            minimum_trade_size=Decimal(str(item.get("minimumTradeSize", "1"))),
            maximum_order_units=Decimal(str(maximum)) if maximum is not None else None,
        )
        self._instrument_specs[instrument] = spec
        return spec

    def candles(self, instrument: str, granularity: str, count: int) -> list[Candle]:
        payload = self._request(
            "GET",
            f"/v3/instruments/{instrument}/candles",
            params={"price": "M", "granularity": granularity, "count": min(count, 5000)},
        )
        candles: list[Candle] = []
        for item in payload.get("candles", []):
            if not item.get("complete", False):
                continue
            mid = item["mid"]
            candles.append(
                Candle(
                    time=datetime.fromisoformat(str(item["time"]).replace("Z", "+00:00")),
                    open=Decimal(mid["o"]),
                    high=Decimal(mid["h"]),
                    low=Decimal(mid["l"]),
                    close=Decimal(mid["c"]),
                    volume=int(item.get("volume", 0)),
                    complete=True,
                )
            )
        return candles

    def quote(self, instrument: str) -> Quote:
        payload = self._request(
            "GET",
            f"/v3/accounts/{self._account_id()}/pricing",
            params={"instruments": instrument},
        )
        prices = payload.get("prices", [])
        if not prices:
            raise OandaApiError(f"no price returned for {instrument}")
        price = prices[0]
        if str(price.get("status", "tradeable")).lower() != "tradeable":
            raise OandaApiError(f"{instrument} is not tradeable")
        bids = price.get("bids", [])
        asks = price.get("asks", [])
        if not bids or not asks:
            raise OandaApiError(f"{instrument} has no executable bid/ask liquidity")
        bid = Decimal(bids[0]["price"])
        ask = Decimal(asks[0]["price"])
        observed = datetime.fromisoformat(str(price["time"]).replace("Z", "+00:00"))
        return Quote(instrument, bid, ask, observed)

    def account(self) -> AccountSnapshot:
        payload = self._request("GET", f"/v3/accounts/{self._account_id()}/summary")
        account = payload["account"]
        return AccountSnapshot(
            account_id=str(account["id"]),
            currency=str(account["currency"]),
            balance=Decimal(account["balance"]),
            nav=Decimal(account["NAV"]),
            margin_used=Decimal(account.get("marginUsed", "0")),
            margin_available=Decimal(account.get("marginAvailable", "0")),
            unrealized_pl=Decimal(account.get("unrealizedPL", "0")),
            open_position_count=int(account.get("openPositionCount", 0)),
            realized_pl_today=self.realized_pl_today(),
        )

    def realized_pl_today(self) -> Decimal:
        now = datetime.now(UTC)
        if self._daily_pl_cache is not None:
            cached_date, cached_at, cached_value = self._daily_pl_cache
            if cached_date == now.date() and time.monotonic() - cached_at < 30:
                return cached_value
        start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        index = self._request(
            "GET",
            f"/v3/accounts/{self._account_id()}/transactions",
            params={
                "from": start.isoformat().replace("+00:00", "Z"),
                "to": now.isoformat().replace("+00:00", "Z"),
                "pageSize": 1000,
                "type": "ORDER_FILL,DAILY_FINANCING",
            },
        )
        total = Decimal("0")
        for page_url in index.get("pages", []):
            page = self._request_page(str(page_url))
            for transaction in page.get("transactions", []):
                for field in (
                    "pl",
                    "financing",
                    "commission",
                    "guaranteedExecutionFee",
                    "dividendAdjustment",
                ):
                    total += Decimal(str(transaction.get(field, "0")))
        self._daily_pl_cache = (now.date(), time.monotonic(), total)
        return total

    def has_open_position(self, instrument: str) -> bool:
        payload = self._request("GET", f"/v3/accounts/{self._account_id()}/openPositions")
        for position in payload.get("positions", []):
            if str(position.get("instrument", "")).upper() != instrument.upper():
                continue
            long_units = Decimal(str(position.get("long", {}).get("units", "0")))
            short_units = Decimal(str(position.get("short", {}).get("units", "0")))
            if long_units != 0 or short_units != 0:
                return True
        return False

    def place_market_order(self, request: OrderRequest) -> OrderResult:
        spec = self.instrument_spec(request.instrument)
        if abs(Decimal(request.units)) < spec.minimum_trade_size:
            raise OandaApiError(
                f"order size is below the broker minimum for {request.instrument}"
            )
        if (
            spec.maximum_order_units is not None
            and abs(Decimal(request.units)) > spec.maximum_order_units
        ):
            raise OandaApiError(
                f"order size exceeds the broker maximum for {request.instrument}"
            )
        body = {
            "order": {
                "type": "MARKET",
                "timeInForce": "FOK",
                "instrument": request.instrument,
                "units": spec.format_units(request.units),
                "positionFill": "DEFAULT",
                "clientExtensions": {
                    "id": request.client_order_id,
                    "tag": "forex-trader",
                    "comment": request.execution_key[:128],
                },
                "stopLossOnFill": {
                    "timeInForce": "GTC",
                    "price": spec.format_price(request.stop_loss),
                },
                "takeProfitOnFill": {
                    "timeInForce": "GTC",
                    "price": spec.format_price(request.take_profit),
                },
            }
        }
        try:
            payload = self._request(
                "POST",
                f"/v3/accounts/{self._account_id()}/orders",
                retry_safe=False,
                json=body,
            )
        except OandaOrderStateUnknown as exc:
            return OrderResult(
                client_order_id=request.client_order_id,
                provider_order_id=None,
                status=OrderStatus.UNKNOWN,
                instrument=request.instrument,
                units=request.units,
                fill_price=None,
                raw={"error": str(exc)},
            )
        fill = payload.get("orderFillTransaction")
        reject = payload.get("orderRejectTransaction")
        if fill:
            return OrderResult(
                client_order_id=request.client_order_id,
                provider_order_id=str(fill.get("orderID") or fill.get("id")),
                status=OrderStatus.FILLED,
                instrument=request.instrument,
                units=int(Decimal(fill.get("units", request.units))),
                fill_price=Decimal(fill["price"]),
                provider_trade_id=(
                    str(fill.get("tradeOpened", {}).get("tradeID"))
                    if fill.get("tradeOpened", {}).get("tradeID") is not None
                    else None
                ),
                raw=payload,
            )
        if reject:
            return OrderResult(
                client_order_id=request.client_order_id,
                provider_order_id=str(reject.get("id")),
                status=OrderStatus.REJECTED,
                instrument=request.instrument,
                units=request.units,
                fill_price=None,
                raw=payload,
            )
        return OrderResult(
            client_order_id=request.client_order_id,
            provider_order_id=None,
            status=OrderStatus.UNKNOWN,
            instrument=request.instrument,
            units=request.units,
            fill_price=None,
            raw=payload,
        )

    def close_trade(self, trade_id: str, units: str = "ALL") -> dict[str, Any]:
        if not trade_id:
            raise ValueError("trade_id is required")
        return self._request(
            "PUT",
            f"/v3/accounts/{self._account_id()}/trades/{trade_id}/close",
            retry_safe=False,
            json={"units": units},
        )

    def practice_probe(self, instrument: str = "EUR_USD") -> dict[str, Any]:
        account = self.account()
        spec = self.instrument_spec(instrument)
        quote = self.quote(instrument)
        candles = self.candles(instrument, "M5", 10)
        return {
            "account_id_suffix": account.account_id[-6:],
            "currency": account.currency,
            "balance": str(account.balance),
            "nav": str(account.nav),
            "instrument": instrument,
            "display_precision": spec.display_precision,
            "minimum_trade_size": str(spec.minimum_trade_size),
            "bid": str(quote.bid),
            "ask": str(quote.ask),
            "completed_candles": len(candles),
            "open_position": self.has_open_position(instrument),
        }

    def _request_page(self, page_url: str) -> dict[str, Any]:
        if not page_url.startswith(f"{self.rest_url}/"):
            raise OandaApiError(
                "OANDA transaction page URL did not match the configured practice host"
            )
        return self._request("GET", page_url[len(self.rest_url) :])

    def _request(
        self,
        method: str,
        path: str,
        *,
        retry_safe: bool = True,
        **kwargs: Any,
    ) -> dict[str, Any]:
        response: httpx.Response | None = None
        attempts = self.max_retries + 1 if retry_safe else 1
        for attempt in range(attempts):
            try:
                response = self.client.request(method, f"{self.rest_url}{path}", **kwargs)
            except httpx.HTTPError as exc:
                if not retry_safe:
                    raise OandaOrderStateUnknown(
                        f"OANDA {method} transport outcome is unknown: {type(exc).__name__}"
                    ) from exc
                if attempt >= attempts - 1:
                    raise OandaApiError(
                        f"OANDA transport error: {type(exc).__name__}"
                    ) from exc
                self._sleeper(0.25 * (attempt + 1))
                continue

            retryable = response.status_code in {429, 500, 502, 503, 504}
            if retryable and not retry_safe:
                raise OandaOrderStateUnknown(
                    f"OANDA {method} returned HTTP {response.status_code}; outcome is unknown"
                )
            if not retryable or attempt >= attempts - 1:
                break
            self._sleeper(0.25 * (attempt + 1))

        assert response is not None
        if response.status_code >= 400:
            request_id = response.headers.get("RequestID") or response.headers.get(
                "request-id"
            )
            detail = response.text[:300].replace("\n", " ")
            suffix = f" request_id={request_id}" if request_id else ""
            raise OandaApiError(
                f"OANDA HTTP {response.status_code}:{suffix} {detail}".strip()
            )
        try:
            return response.json()
        except ValueError as exc:
            raise OandaApiError("OANDA returned invalid JSON") from exc
