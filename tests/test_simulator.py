from decimal import Decimal

from forex_trader.adapters.simulator import SimulatedPaperBroker
from forex_trader.adapters.synthetic import SyntheticMarketData
from forex_trader.domain.enums import Direction, OrderStatus
from forex_trader.domain.models import OrderRequest


def test_simulator_fills_and_tracks_order() -> None:
    market = SyntheticMarketData()
    broker = SimulatedPaperBroker(market, balance=Decimal("10000"))
    result = broker.place_market_order(
        OrderRequest("client-1", "EUR_USD", Direction.LONG, 100, Decimal("1.09"), Decimal("1.12"))
    )
    assert result.status is OrderStatus.FILLED
    assert result.fill_price == market.quote("EUR_USD").ask
    assert broker.account().open_position_count == 1
