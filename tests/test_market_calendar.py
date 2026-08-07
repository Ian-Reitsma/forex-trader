from datetime import UTC, datetime
from decimal import Decimal

import pytest

from forex_trader.adapters.simulator import SimulatedPaperBroker
from forex_trader.adapters.synthetic import SyntheticMarketData
from forex_trader.application.engine import TradingEngine
from forex_trader.domain.enums import DecisionDisposition, OperatingMode
from forex_trader.domain.events import pair_event_blackout
from forex_trader.domain.fundamentals import FundamentalBook
from forex_trader.domain.market_calendar import currency_holiday, pair_holiday_blackout
from forex_trader.domain.models import CurrencyFundamentals
from forex_trader.domain.risk import RiskPolicy
from forex_trader.domain.strategy import SignalFusionPolicy
from forex_trader.infrastructure.trading_repository import TradingRepository


def test_currency_holiday_detects_target2_and_us_new_year() -> None:
    instant = datetime(2026, 1, 1, 12, tzinfo=UTC)
    eur = currency_holiday("EUR", instant)
    usd = currency_holiday("USD", instant)
    assert eur is not None
    assert eur.calendar_code == "XECB"
    assert usd is not None
    assert usd.calendar_code == "US"


def test_currency_holiday_ignores_unknown_currency_and_normal_day() -> None:
    ordinary = datetime(2026, 1, 2, 12, tzinfo=UTC)
    assert currency_holiday("XXX", ordinary) is None
    assert pair_holiday_blackout("EUR_USD", ordinary) == (False, ())


def test_holiday_checks_validate_time_and_pair_format() -> None:
    with pytest.raises(ValueError, match="timezone-aware"):
        currency_holiday("USD", datetime(2026, 1, 1, 12))
    with pytest.raises(ValueError, match="BASE_QUOTE"):
        pair_holiday_blackout("EURUSD", datetime(2026, 1, 1, 12, tzinfo=UTC))


def test_pair_event_blackout_combines_market_holiday_reasons() -> None:
    blocked, reasons = pair_event_blackout(
        "EUR_USD",
        datetime(2026, 1, 1, 12, tzinfo=UTC),
        [],
    )
    assert blocked is True
    assert reasons
    assert all("MARKET_HOLIDAY" in reason for reason in reasons)


def test_engine_never_submits_qualifying_setup_on_currency_holiday() -> None:
    anchor = datetime(2026, 1, 1, 18, tzinfo=UTC)
    market = SyntheticMarketData(seed=11, direction="long", anchor=anchor)
    broker = SimulatedPaperBroker(market)
    engine = TradingEngine(
        market_data=market,
        broker=broker,
        repository=TradingRepository(":memory:"),
        fundamentals=FundamentalBook(
            [
                CurrencyFundamentals(
                    "EUR", policy=Decimal("0.5"), confidence=Decimal("0.9"), as_of=anchor
                ),
                CurrencyFundamentals(
                    "USD", policy=Decimal("-0.5"), confidence=Decimal("0.9"), as_of=anchor
                ),
            ]
        ),
        fusion_policy=SignalFusionPolicy(minimum_score=Decimal("0.5")),
        risk_policy=RiskPolicy(),
        mode=OperatingMode.PAPER,
        enable_paper_orders=True,
    )
    trace = engine.evaluate("EUR_USD", execute=True)
    assert trace.candidate.disposition is DecisionDisposition.ABSTAIN
    assert trace.candidate.rejection_code == "EVENT_BLACKOUT"
    assert any("MARKET_HOLIDAY" in reason for reason in trace.candidate.reasons)
    assert trace.order is None
    assert broker.orders == []
