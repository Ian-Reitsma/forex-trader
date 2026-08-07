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


def test_simulator_positions_conversion_and_reconciliation() -> None:
    market = SyntheticMarketData()
    broker = SimulatedPaperBroker(market)
    order = broker.place_market_order(
        OrderRequest("client-2", "EUR_USD", Direction.SHORT, -50, Decimal("1.12"), Decimal("1.09"))
    )
    assert broker.positions()[0].short_units == Decimal("-50")
    assert broker.has_open_position("EUR_USD") is True
    assert broker.conversion_rate("USD", "USD") == Decimal("1")
    assert broker.reconcile_order(client_order_id="client-2", instrument="EUR_USD", units=-50) == order
    assert broker.reconcile_order(client_order_id="missing", instrument="EUR_USD", units=1) is None
