from forex_trader.domain.enums import DecisionDisposition, OrderStatus, RiskDisposition


def test_end_to_end_engine_executes_paper_order(engine) -> None:  # type: ignore[no-untyped-def]
    trace = engine.evaluate("EUR_USD", execute=True)
    assert trace.candidate.disposition is DecisionDisposition.TRADE
    assert trace.risk is not None
    assert trace.risk.disposition is RiskDisposition.GRANTED
    assert trace.order is not None
    assert trace.order.status is OrderStatus.FILLED


def test_engine_does_not_execute_without_flag(engine) -> None:  # type: ignore[no-untyped-def]
    trace = engine.evaluate("EUR_USD", execute=False)
    assert trace.order is None


def test_engine_blocks_repeated_submission_for_same_signal(market, fundamentals) -> None:  # type: ignore[no-untyped-def]
    from forex_trader.adapters.simulator import SimulatedPaperBroker
    from forex_trader.application.engine import TradingEngine
    from forex_trader.domain.enums import OperatingMode, RiskDisposition
    from forex_trader.domain.risk import RiskPolicy
    from forex_trader.domain.strategy import SignalFusionPolicy
    from forex_trader.infrastructure.repository import SqliteDecisionRepository
    from decimal import Decimal

    class PositionBlindBroker(SimulatedPaperBroker):
        def positions(self):  # type: ignore[no-untyped-def]
            return []

        def has_open_position(self, instrument: str) -> bool:
            return False

    repository = SqliteDecisionRepository(":memory:")
    broker = PositionBlindBroker(market)
    local_engine = TradingEngine(
        market_data=market,
        broker=broker,
        repository=repository,
        fundamentals=fundamentals,
        fusion_policy=SignalFusionPolicy(minimum_score=Decimal("0.5")),
        risk_policy=RiskPolicy(),
        mode=OperatingMode.PAPER,
        enable_paper_orders=True,
    )
    first = local_engine.evaluate("EUR_USD", execute=True)
    second = local_engine.evaluate("EUR_USD", execute=True)
    assert first.order is not None
    assert second.order is None
    assert second.risk is not None
    assert second.risk.disposition is RiskDisposition.DENIED
    assert "already submitted" in second.risk.reasons[0]
    assert len(broker.orders) == 1


def test_engine_blocks_stacking_same_instrument(engine) -> None:  # type: ignore[no-untyped-def]
    from forex_trader.domain.enums import RiskDisposition

    first = engine.evaluate("EUR_USD", execute=True)
    second = engine.evaluate("EUR_USD", execute=True)
    assert first.order is not None
    assert second.order is None
    assert second.risk is not None
    assert second.risk.disposition is RiskDisposition.DENIED
    assert "open position" in second.risk.reasons[0]


def test_engine_persists_fundamental_observations(engine) -> None:  # type: ignore[no-untyped-def]
    from decimal import Decimal

    engine.ingest_release(
        currency="USD",
        category="labor",
        actual=Decimal("250"),
        forecast=Decimal("200"),
        previous=Decimal("180"),
    )
    engine.ingest_news(currency="EUR", headline="growth strong")
    history = engine.repository.macro_observations()  # type: ignore[attr-defined]
    assert len(history) == 2
    assert {item.currency for item in history} == {"EUR", "USD"}


def test_engine_reconciles_unknown_order_before_recording(market, fundamentals) -> None:  # type: ignore[no-untyped-def]
    from decimal import Decimal
    from forex_trader.adapters.simulator import SimulatedPaperBroker
    from forex_trader.application.engine import TradingEngine
    from forex_trader.domain.enums import OperatingMode, OrderStatus
    from forex_trader.domain.models import OrderResult
    from forex_trader.domain.risk import RiskPolicy
    from forex_trader.domain.strategy import SignalFusionPolicy
    from forex_trader.infrastructure.repository import SqliteDecisionRepository

    class UnknownThenFilledBroker(SimulatedPaperBroker):
        def place_market_order(self, request):  # type: ignore[no-untyped-def]
            self.request = request
            return OrderResult(
                request.client_order_id,
                None,
                OrderStatus.UNKNOWN,
                request.instrument,
                request.units,
                None,
            )

        def reconcile_order(self, *, client_order_id: str, instrument: str, units: int):  # type: ignore[no-untyped-def]
            return OrderResult(
                client_order_id,
                "provider-1",
                OrderStatus.FILLED,
                instrument,
                units,
                market.quote(instrument).ask,
                provider_trade_id="trade-1",
            )

        def has_open_position(self, instrument: str) -> bool:
            return False

    repository = SqliteDecisionRepository(":memory:")
    broker = UnknownThenFilledBroker(market)
    local_engine = TradingEngine(
        market_data=market,
        broker=broker,
        repository=repository,
        fundamentals=fundamentals,
        fusion_policy=SignalFusionPolicy(minimum_score=Decimal("0.5")),
        risk_policy=RiskPolicy(),
        mode=OperatingMode.PAPER,
        enable_paper_orders=True,
    )
    trace = local_engine.evaluate("EUR_USD", execute=True)
    assert trace.order is not None
    assert trace.order.status is OrderStatus.FILLED
    assert any(sample.slippage_pips is not None for sample in repository.cost_samples())
