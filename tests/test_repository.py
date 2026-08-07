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
