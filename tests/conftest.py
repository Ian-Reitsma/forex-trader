from decimal import Decimal

import pytest

from forex_trader.adapters.simulator import SimulatedPaperBroker
from forex_trader.adapters.synthetic import SyntheticMarketData
from forex_trader.application.engine import TradingEngine
from forex_trader.domain.enums import OperatingMode
from forex_trader.domain.fundamentals import FundamentalBook
from forex_trader.domain.models import CurrencyFundamentals
from forex_trader.domain.risk import RiskPolicy
from forex_trader.domain.strategy import SignalFusionPolicy
from forex_trader.infrastructure.repository import SqliteDecisionRepository


@pytest.fixture()
def market() -> SyntheticMarketData:
    return SyntheticMarketData(seed=11, direction="long")


@pytest.fixture()
def fundamentals() -> FundamentalBook:
    return FundamentalBook(
        [
            CurrencyFundamentals(
                "EUR",
                policy=Decimal("0.4"),
                inflation=Decimal("0.2"),
                growth=Decimal("0.2"),
                labor=Decimal("0.1"),
                confidence=Decimal("0.9"),
            ),
            CurrencyFundamentals(
                "USD",
                policy=Decimal("-0.2"),
                inflation=Decimal("-0.1"),
                growth=Decimal("-0.1"),
                labor=Decimal("0"),
                confidence=Decimal("0.9"),
            ),
        ]
    )


@pytest.fixture()
def engine(market: SyntheticMarketData, fundamentals: FundamentalBook) -> TradingEngine:
    return TradingEngine(
        market_data=market,
        broker=SimulatedPaperBroker(market),
        repository=SqliteDecisionRepository(":memory:"),
        fundamentals=fundamentals,
        fusion_policy=SignalFusionPolicy(minimum_score=Decimal("0.50")),
        risk_policy=RiskPolicy(),
        mode=OperatingMode.PAPER,
        enable_paper_orders=True,
    )
