from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

import httpx

from forex_trader.adapters.oanda import OandaApiError, OandaPracticeClient
from forex_trader.domain.enums import OrderStatus
from forex_trader.domain.instruments import register_spec
from forex_trader.domain.models import InstrumentSpec, OrderRequest, OrderResult, Quote


class SafeOandaPracticeClient(OandaPracticeClient):
    """Practice-only adapter with price bounds, reject mapping and protection verification."""

    def instrument_spec(self, instrument: str) -> InstrumentSpec:
        instrument = instrument.upper()
        cached = self._instrument_specs.get(instrument)
        if cached is not None:
            register_spec(cached)
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
        maximum_position = item.get("maximumPositionSize")
        margin_rate = item.get("marginRate")
        spec = InstrumentSpec(
            name=str(item["name"]),
            display_precision=int(item["displayPrecision"]),
            pip_location=int(item["pipLocation"]),
            trade_units_precision=int(item.get("tradeUnitsPrecision", 0)),
            minimum_trade_size=Decimal(str(item.get("minimumTradeSize", "1"))),
            maximum_order_units=Decimal(str(maximum)) if maximum is not None else None,
            maximum_position_size=(Decimal(str(maximum_position)) if maximum_position is not None else None),
            margin_rate=Decimal(str(margin_rate)) if margin_rate is not None else None,
        )
        self._instrument_specs[instrument] = spec
        register_spec(spec)
        return spec

    def quote(self, instrument: str) -> Quote:
        return self.quote_for_units(instrument, units=None)

    def quote_for_units(self, instrument: str, units: int | None) -> Quote:
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
        required = Decimal(abs(units)) if units is not None else Decimal("0")
        bid, bid_liquidity = _bucket_price(bids, required)
        ask, ask_liquidity = _bucket_price(asks, required)
        observed = datetime.fromisoformat(str(price["time"]).replace("Z", "+00:00"))
        return Quote(
            instrument.upper(),
            bid,
            ask,
            observed,
            bid_liquidity=bid_liquidity,
            ask_liquidity=ask_liquidity,
        )

    def currency_instruments(self) -> list[InstrumentSpec]:
        payload = self._request("GET", f"/v3/accounts/{self._account_id()}/instruments")
        specs: list[InstrumentSpec] = []
        for item in payload.get("instruments", []):
            if str(item.get("type", "CURRENCY")).upper() != "CURRENCY":
                continue
            maximum = item.get("maximumOrderUnits")
            maximum_position = item.get("maximumPositionSize")
            margin_rate = item.get("marginRate")
            spec = InstrumentSpec(
                name=str(item["name"]),
                display_precision=int(item["displayPrecision"]),
                pip_location=int(item["pipLocation"]),
                trade_units_precision=int(item.get("tradeUnitsPrecision", 0)),
                minimum_trade_size=Decimal(str(item.get("minimumTradeSize", "1"))),
                maximum_order_units=Decimal(str(maximum)) if maximum is not None else None,
                maximum_position_size=Decimal(str(maximum_position)) if maximum_position is not None else None,
                margin_rate=Decimal(str(margin_rate)) if margin_rate is not None else None,
            )
            self._instrument_specs[spec.name.upper()] = spec
            register_spec(spec)
            specs.append(spec)
        return sorted(specs, key=lambda item: item.name)

    def place_market_order(self, request: OrderRequest) -> OrderResult:
        if not self.account_id:
            raise OandaApiError("OANDA_ACCOUNT_ID is required for broker writes")
        spec = self.instrument_spec(request.instrument)
        absolute_units = abs(Decimal(request.units))
        if absolute_units < spec.minimum_trade_size:
            raise OandaApiError(f"order size is below the broker minimum for {request.instrument}")
        if spec.maximum_order_units is not None and absolute_units > spec.maximum_order_units:
            raise OandaApiError(f"order size exceeds the broker maximum for {request.instrument}")
        if spec.maximum_position_size is not None and spec.maximum_position_size > 0 and absolute_units > spec.maximum_position_size:
            raise OandaApiError(f"order size exceeds the broker position maximum for {request.instrument}")

        order: dict[str, Any] = {
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
            "stopLossOnFill": {"timeInForce": "GTC", "price": spec.format_price(request.stop_loss)},
            "takeProfitOnFill": {"timeInForce": "GTC", "price": spec.format_price(request.take_profit)},
        }
        if request.price_bound is not None:
            order["priceBound"] = spec.format_price(request.price_bound)
        payload, status_code = self._write_json(
            "POST",
            f"/v3/accounts/{self.account_id}/orders",
            json={"order": order},
        )
        reject = payload.get("orderRejectTransaction")
        if reject is not None:
            return OrderResult(
                client_order_id=request.client_order_id,
                provider_order_id=str(reject.get("id") or "") or None,
                status=OrderStatus.REJECTED,
                instrument=request.instrument,
                units=request.units,
                fill_price=None,
                raw=payload,
                broker_time=_broker_time(reject),
            )
        if status_code >= 400:
            raise OandaApiError(
                f"OANDA HTTP {status_code}: {str(payload.get('errorMessage') or payload.get('errorCode') or 'order rejected')[:240]}",
                status_code=status_code,
            )
        fill = payload.get("orderFillTransaction")
        if not isinstance(fill, dict):
            return OrderResult(
                request.client_order_id,
                None,
                OrderStatus.UNKNOWN,
                request.instrument,
                request.units,
                None,
                raw=payload,
            )
        opened = fill.get("tradeOpened")
        trade_id = str(opened.get("tradeID")) if isinstance(opened, dict) and opened.get("tradeID") is not None else None
        return OrderResult(
            client_order_id=request.client_order_id,
            provider_order_id=str(fill.get("orderID") or fill.get("id") or "") or None,
            status=OrderStatus.FILLED,
            instrument=str(fill.get("instrument") or request.instrument),
            units=int(Decimal(str(fill.get("units", request.units)))),
            fill_price=Decimal(str(fill["price"])) if fill.get("price") is not None else None,
            provider_trade_id=trade_id,
            raw=payload,
            broker_time=_broker_time(fill),
        )

    def verify_trade_protection(
        self,
        trade_id: str,
        *,
        stop_loss: Decimal,
        take_profit: Decimal,
    ) -> bool:
        payload = self._request("GET", f"/v3/accounts/{self._account_id()}/trades/{trade_id}")
        trade = payload.get("trade", {})
        if not isinstance(trade, dict):
            return False
        stop = trade.get("stopLossOrder")
        take = trade.get("takeProfitOrder")
        if not isinstance(stop, dict) or not isinstance(take, dict):
            return False
        spec = self.instrument_spec(str(trade.get("instrument") or ""))
        expected_stop = spec.format_price(stop_loss)
        expected_take = spec.format_price(take_profit)
        return str(stop.get("state", "PENDING")).upper() == "PENDING" and str(take.get("state", "PENDING")).upper() == "PENDING" and spec.format_price(Decimal(str(stop.get("price")))) == expected_stop and spec.format_price(Decimal(str(take.get("price")))) == expected_take

    def ensure_trade_protection(
        self,
        trade_id: str,
        *,
        stop_loss: Decimal,
        take_profit: Decimal,
    ) -> bool:
        if self.verify_trade_protection(trade_id, stop_loss=stop_loss, take_profit=take_profit):
            return True
        spec = self.instrument_spec(self._trade_instrument(trade_id))
        payload, status = self._write_json(
            "PUT",
            f"/v3/accounts/{self._account_id()}/trades/{trade_id}/orders",
            json={
                "stopLoss": {"timeInForce": "GTC", "price": spec.format_price(stop_loss)},
                "takeProfit": {"timeInForce": "GTC", "price": spec.format_price(take_profit)},
            },
        )
        if status >= 400 or payload.get("stopLossOrderRejectTransaction") or payload.get("takeProfitOrderRejectTransaction"):
            return False
        return self.verify_trade_protection(trade_id, stop_loss=stop_loss, take_profit=take_profit)

    def transactions_between(self, start: datetime, end: datetime) -> list[dict[str, Any]]:
        if start.tzinfo is None or end.tzinfo is None or end <= start:
            raise ValueError("transaction range must be timezone-aware and increasing")
        transactions: list[dict[str, Any]] = []
        cursor = start.astimezone(UTC)
        final = end.astimezone(UTC)
        while cursor < final:
            window_end = min(final, cursor + timedelta(days=364))
            index = self._request(
                "GET",
                f"/v3/accounts/{self._account_id()}/transactions",
                params={
                    "from": cursor.isoformat().replace("+00:00", "Z"),
                    "to": window_end.isoformat().replace("+00:00", "Z"),
                    "pageSize": 1000,
                },
            )
            for page_url in index.get("pages", []):
                page = self._request_page(str(page_url))
                transactions.extend(dict(item) for item in page.get("transactions", []) if isinstance(item, dict))
            cursor = window_end
        return transactions

    def _trade_instrument(self, trade_id: str) -> str:
        payload = self._request("GET", f"/v3/accounts/{self._account_id()}/trades/{trade_id}")
        trade = payload.get("trade", {})
        instrument = str(trade.get("instrument") or "") if isinstance(trade, dict) else ""
        if not instrument:
            raise OandaApiError(f"trade {trade_id} did not expose an instrument")
        return instrument

    def _write_json(self, method: str, path: str, **kwargs: Any) -> tuple[dict[str, Any], int]:
        try:
            response = self.client.request(method, f"{self.rest_url}{path}", **kwargs)
        except httpx.HTTPError as exc:
            # A transport failure can occur after OANDA accepted a write. The caller
            # must reconcile rather than resubmit.
            return {"error": f"transport outcome unknown: {type(exc).__name__}"}, 599
        if response.status_code in {429, 500, 502, 503, 504}:
            return {"error": f"HTTP {response.status_code} outcome unknown"}, response.status_code
        try:
            payload = response.json()
        except ValueError:
            payload = {"errorMessage": response.text[:240]}
        return dict(payload), response.status_code


def _bucket_price(buckets: list[dict[str, Any]], required: Decimal) -> tuple[Decimal, Decimal | None]:
    total = Decimal("0")
    selected: Decimal | None = None
    for bucket in buckets:
        price = Decimal(str(bucket["price"]))
        liquidity = Decimal(str(bucket.get("liquidity", "0")))
        total += max(Decimal("0"), liquidity)
        selected = price
        if required <= 0 or total >= required:
            return price, total if total > 0 else None
    if required > 0:
        raise OandaApiError(f"executable pricing liquidity {total} is below requested units {required}")
    assert selected is not None
    return selected, total if total > 0 else None


def _broker_time(payload: dict[str, Any]) -> datetime | None:
    value = payload.get("time")
    if value is None:
        return None
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
