from __future__ import annotations

from decimal import Decimal
from itertools import count

from forex_trader.adapters.synthetic import SyntheticMarketData
from forex_trader.domain.enums import Direction, OrderStatus
from forex_trader.domain.models import AccountSnapshot, OrderRequest, OrderResult
from forex_trader.domain.portfolio import OpenPosition


class SimulatedPaperBroker:
    def __init__(
        self,
        market_data: SyntheticMarketData,
        *,
        balance: Decimal = Decimal("100000"),
        currency: str = "USD",
    ) -> None:
        self.market_data = market_data
        self._balance = balance
        self._currency = currency
        self._orders: list[OrderResult] = []
        self._sequence = count(1)

    def account(self) -> AccountSnapshot:
        return AccountSnapshot(
            account_id="SIM-001",
            currency=self._currency,
            balance=self._balance,
            nav=self._balance,
            open_position_count=len(self.positions()),
        )

    def positions(self) -> list[OpenPosition]:
        results: list[OpenPosition] = []
        for order in self._orders:
            if order.status is not OrderStatus.FILLED or order.fill_price is None:
                continue
            if order.units > 0:
                results.append(
                    OpenPosition(
                        instrument=order.instrument,
                        long_units=Decimal(order.units),
                        long_average_price=order.fill_price,
                    )
                )
            elif order.units < 0:
                results.append(
                    OpenPosition(
                        instrument=order.instrument,
                        short_units=Decimal(order.units),
                        short_average_price=order.fill_price,
                    )
                )
        return results

    def has_open_position(self, instrument: str) -> bool:
        return any(
            position.instrument == instrument.upper() and position.net_units != 0
            for position in self.positions()
        )

    def conversion_rate(self, from_currency: str, to_currency: str) -> Decimal | None:
        source = from_currency.upper()
        target = to_currency.upper()
        if source == target:
            return Decimal("1")
        direct = f"{source}_{target}"
        try:
            return self.market_data.quote(direct).mid
        except Exception:
            inverse = f"{target}_{source}"
            try:
                mid = self.market_data.quote(inverse).mid
                return None if mid <= 0 else Decimal("1") / mid
            except Exception:
                return None

    def place_market_order(self, request: OrderRequest) -> OrderResult:
        quote = self.market_data.quote(request.instrument)
        fill = quote.ask if request.direction is Direction.LONG else quote.bid
        result = OrderResult(
            client_order_id=request.client_order_id,
            provider_order_id=f"SIM-{next(self._sequence)}",
            status=OrderStatus.FILLED,
            instrument=request.instrument,
            units=request.units,
            fill_price=fill,
            provider_trade_id=f"SIM-TRADE-{len(self._orders) + 1}",
            raw={
                "stop_loss": str(request.stop_loss),
                "take_profit": str(request.take_profit),
                "provider": "simulation",
            },
        )
        self._orders.append(result)
        return result

    def reconcile_order(
        self,
        *,
        client_order_id: str,
        instrument: str,
        units: int,
    ) -> OrderResult | None:
        for order in self._orders:
            if order.client_order_id == client_order_id:
                return order
        return None

    @property
    def orders(self) -> list[OrderResult]:
        return list(self._orders)
