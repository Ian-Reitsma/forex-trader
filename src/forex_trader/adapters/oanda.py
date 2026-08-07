from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any

import httpx

from forex_trader.domain.enums import Direction, OrderStatus
from forex_trader.domain.models import AccountSnapshot, Candle, OrderRequest, OrderResult, Quote


class OandaApiError(RuntimeError):
    pass


class OandaPracticeClient:
    def __init__(
        self,
        *,
        token: str,
        account_id: str | None,
        rest_url: str = "https://api-fxpractice.oanda.com",
        timeout_seconds: float = 10.0,
        client: httpx.Client | None = None,
    ) -> None:
        if not token:
            raise ValueError("OANDA token is required")
        self.token = token
        self.account_id = account_id
        self.rest_url = rest_url.rstrip("/")
        self._owns_client = client is None
        self.client = client or httpx.Client(
            timeout=timeout_seconds,
            headers={
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json",
                "Accept-Datetime-Format": "RFC3339",
                "User-Agent": "forex-trader/0.1",
            },
        )

    def close(self) -> None:
        if self._owns_client:
            self.client.close()

    def discover_account_id(self) -> str:
        payload = self._request("GET", "/v3/accounts")
        accounts = payload.get("accounts", [])
        if not accounts:
            raise OandaApiError("the token does not expose any accounts")
        self.account_id = str(accounts[0]["id"])
        return self.account_id

    def _account_id(self) -> str:
        return self.account_id or self.discover_account_id()

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
        bid = Decimal(price["bids"][0]["price"])
        ask = Decimal(price["asks"][0]["price"])
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
            margin_used=Decimal(account["marginUsed"]),
            unrealized_pl=Decimal(account["unrealizedPL"]),
            open_position_count=int(account["openPositionCount"]),
            realized_pl_today=Decimal("0"),
        )

    def place_market_order(self, request: OrderRequest) -> OrderResult:
        body = {
            "order": {
                "type": "MARKET",
                "timeInForce": "FOK",
                "instrument": request.instrument,
                "units": str(request.units),
                "positionFill": "DEFAULT",
                "clientExtensions": {"id": request.client_order_id, "tag": "forex-trader"},
                "stopLossOnFill": {"timeInForce": "GTC", "price": str(request.stop_loss)},
                "takeProfitOnFill": {"timeInForce": "GTC", "price": str(request.take_profit)},
            }
        }
        payload = self._request("POST", f"/v3/accounts/{self._account_id()}/orders", json=body)
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

    def _request(self, method: str, path: str, **kwargs: Any) -> dict[str, Any]:
        try:
            response = self.client.request(method, f"{self.rest_url}{path}", **kwargs)
        except httpx.HTTPError as exc:
            raise OandaApiError(f"OANDA transport error: {exc}") from exc
        if response.status_code >= 400:
            detail = response.text[:500]
            raise OandaApiError(f"OANDA HTTP {response.status_code}: {detail}")
        try:
            return response.json()
        except ValueError as exc:
            raise OandaApiError("OANDA returned invalid JSON") from exc
