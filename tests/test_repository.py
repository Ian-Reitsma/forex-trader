from decimal import Decimal

from forex_trader.adapters.simulator import SimulatedPaperBroker
from forex_trader.adapters.synthetic import SyntheticMarketData
from forex_trader.application.engine import TradingEngine
from forex_trader.domain.enums import OperatingMode
from forex_trader.domain.fundamentals import FundamentalBook
from forex_trader.domain.models import CurrencyFundamentals
from forex_trader.domain.risk import RiskPolicy
from forex_trader.domain.strategy import SignalFusionPolicy
from forex_trader.infrastructure.repository import SqliteDecisionRepository


def test_repository_round_trip() -> None:
    market = SyntheticMarketData(direction="long")
    repository = SqliteDecisionRepository(":memory:")
    engine = TradingEngine(
        market_data=market,
        broker=SimulatedPaperBroker(market),
        repository=repository,
        fundamentals=FundamentalBook(
            [
                CurrencyFundamentals("EUR", policy=Decimal("0.5"), confidence=Decimal("0.9")),
                CurrencyFundamentals("USD", policy=Decimal("-0.5"), confidence=Decimal("0.9")),
            ]
        ),
        fusion_policy=SignalFusionPolicy(minimum_score=Decimal("0.5")),
        risk_policy=RiskPolicy(),
        mode=OperatingMode.SHADOW,
    )
    trace = engine.evaluate("EUR_USD")
    records = repository.recent_traces()
    assert records[0]["trace_id"] == str(trace.trace_id)
    assert records[0]["instrument"] == "EUR_USD"


def test_repository_execution_claim_is_atomic_and_releasable() -> None:
    repository = SqliteDecisionRepository(":memory:")
    assert repository.claim_execution("signal-1") is True
    assert repository.claim_execution("signal-1") is False
    repository.release_execution("signal-1")
    assert repository.claim_execution("signal-1") is True


def test_repository_persists_macro_costs_transactions_and_cursors() -> None:
    from datetime import UTC, datetime
    from forex_trader.domain.costs import CostSample, TradingSession
    from forex_trader.domain.macro_history import MacroObservation

    repository = SqliteDecisionRepository(":memory:")
    observation = MacroObservation.release(
        currency="USD",
        category="labor",
        actual=Decimal("250"),
        forecast=Decimal("200"),
        previous=Decimal("180"),
        higher_is_positive=True,
        available_at=datetime(2026, 1, 1, tzinfo=UTC),
    )
    repository.save_macro_observation(observation)
    loaded = repository.macro_observations()
    assert loaded == [observation]
    assert repository.macro_observations(as_of=datetime(2025, 1, 1, tzinfo=UTC)) == []

    sample = CostSample(
        instrument="EUR_USD",
        observed_at=datetime(2026, 1, 1, 8, tzinfo=UTC),
        session=TradingSession.LONDON,
        spread_pips=Decimal("0.8"),
        slippage_pips=Decimal("0.2"),
    )
    repository.save_cost_sample(sample)
    assert repository.cost_samples() == [sample]

    assert repository.save_broker_transaction({"id": "1", "type": "MARKET_ORDER"}) is True
    assert repository.save_broker_transaction({"id": "1", "type": "MARKET_ORDER"}) is False
    assert repository.broker_transactions()[0]["id"] == "1"
    assert repository.get_broker_cursor("cursor") is None
    repository.set_broker_cursor("cursor", "1")
    assert repository.get_broker_cursor("cursor") == "1"


def test_repository_promotion_metrics_reconstruct_owned_trade() -> None:
    """Promotion accounting must be deterministic and independent of strategy selection."""
    from datetime import UTC, datetime, timedelta
    from uuid import uuid4

    from forex_trader.domain.costs import CostSample, TradingSession
    from forex_trader.domain.enums import DecisionDisposition, Direction, OrderStatus
    from forex_trader.domain.models import DecisionTrace, OrderResult, Quote, TradeCandidate

    repository = SqliteDecisionRepository(":memory:")
    signal_time = datetime(2026, 1, 7, 13, tzinfo=UTC)
    candidate = TradeCandidate(
        candidate_id=uuid4(),
        instrument="EUR_USD",
        direction=Direction.LONG,
        disposition=DecisionDisposition.TRADE,
        score=Decimal("0.8"),
        entry_price=Decimal("1.1000"),
        stop_loss=Decimal("1.0980"),
        take_profit=Decimal("1.1040"),
        technical_score=Decimal("0.8"),
        fundamental_score=Decimal("0.6"),
        reasons=("explicit repository accounting fixture",),
        signal_time=signal_time,
        execution_key="ft-explicit-accounting",
        setup_family="test",
        setup_state="entry_confirmed",
        expires_at=signal_time + timedelta(minutes=10),
    )
    quote = Quote(
        "EUR_USD",
        Decimal("1.0999"),
        Decimal("1.1001"),
        signal_time + timedelta(seconds=1),
    )
    order = OrderResult(
        client_order_id="ft-owned",
        provider_order_id="100",
        status=OrderStatus.FILLED,
        instrument="EUR_USD",
        units=1000,
        fill_price=Decimal("1.1001"),
        provider_trade_id="200",
        protection_confirmed=True,
    )
    repository.save_trace(DecisionTrace.create("EUR_USD", candidate, quote, order=order))
    repository.save_broker_transaction(
        {
            "id": "100",
            "type": "MARKET_ORDER",
            "clientExtensions": {"id": "ft-owned", "tag": "forex-trader"},
        }
    )
    repository.save_broker_transaction(
        {
            "id": "101",
            "type": "ORDER_FILL",
            "orderID": "100",
            "tradeOpened": {"tradeID": "200"},
        }
    )
    repository.save_broker_transaction(
        {
            "id": "102",
            "type": "ORDER_FILL",
            "orderID": "stop-1",
            "tradesClosed": [
                {"tradeID": "200", "realizedPL": "12.5", "financing": "-0.5"}
            ],
        }
    )
    repository.save_cost_sample(
        CostSample(
            instrument="EUR_USD",
            observed_at=datetime(2026, 1, 1, 8, tzinfo=UTC),
            session=TradingSession.LONDON,
            spread_pips=Decimal("0"),
            slippage_pips=Decimal("0.3"),
        )
    )
    metrics = repository.promotion_metrics()
    assert metrics.decisions == 1
    assert metrics.trade_candidates == 1
    assert metrics.submitted_orders == 1
    assert metrics.closed_trades == 1
    assert metrics.wins == 1
    assert metrics.total_pl == Decimal("12.0")
    assert metrics.median_slippage_pips == Decimal("0.3")
