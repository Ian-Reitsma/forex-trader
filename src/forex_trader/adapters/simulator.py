from __future__ import annotations

from decimal import Decimal
from itertools import count

from forex_trader.domain.enums import Direction, OrderStatus
from forex_trader.domain.models import AccountSnapshot, OrderRequest, OrderResult
from forex_trader.adapters.synthetic import SyntheticMarketData


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
            open_position_count=len([o for o in self._orders if o.status is OrderStatus.FILLED]),
        )

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
            raw={
                "stop_loss": str(request.stop_loss),
                "take_profit": str(request.take_profit),
                "provider": "simulation",
            },
        )
        self._orders.append(result)
        return result

    @property
    def orders(self) -> list[OrderResult]:
        return list(self._orders)
