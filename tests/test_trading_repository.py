from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from forex_trader.adapters.simulator import SimulatedPaperBroker
from forex_trader.adapters.synthetic import SyntheticMarketData
from forex_trader.application.engine import TradingEngine
from forex_trader.domain.enums import OperatingMode
from forex_trader.domain.events import ScheduledMacroEvent
from forex_trader.domain.fundamentals import FundamentalBook
from forex_trader.domain.models import CurrencyFundamentals
from forex_trader.domain.risk import RiskPolicy
from forex_trader.domain.strategy import SignalFusionPolicy
from forex_trader.infrastructure.trading_repository import TradingRepository


def test_persistent_halt_lifecycle() -> None:
    repository = TradingRepository(":memory:")
    assert repository.get_halt("global") is None
    repository.set_halt("global", "operator test")
    assert repository.get_halt("global") == "operator test"
    repository.clear_halt("global")
    assert repository.get_halt("global") is None
    with pytest.raises(ValueError):
        repository.set_halt("", "reason")


def test_account_lock_and_risk_day_validate_inputs() -> None:
    repository = TradingRepository(":memory:")
    with pytest.raises(ValueError):
        repository.acquire_account_lock("A", "owner", ttl_seconds=0)
    with pytest.raises(ValueError):
        repository.observe_risk_day(
            account_id="A",
            trading_day="2026-08-07",
            marked_pl=Decimal("-1"),
            loss_limit_amount=Decimal("0"),
        )


def test_scheduled_event_range_filters_and_immutability() -> None:
    repository = TradingRepository(":memory:")
    first = ScheduledMacroEvent.create(
        currency="USD",
        scheduled_at=datetime(2026, 8, 7, 12, tzinfo=UTC),
        name="First",
    )
    second = ScheduledMacroEvent.create(
        currency="EUR",
        scheduled_at=datetime(2026, 8, 7, 14, tzinfo=UTC),
        name="Second",
    )
    repository.save_scheduled_event(first)
    repository.save_scheduled_event(second)
    repository.save_scheduled_event(first)
    selected = repository.scheduled_events(
        start=datetime(2026, 8, 7, 13, tzinfo=UTC),
        end=datetime(2026, 8, 7, 15, tzinfo=UTC),
    )
    assert selected == [second]
    with pytest.raises(ValueError, match="start"):
        repository.scheduled_events(start=datetime(2026, 8, 7, 13))
    with pytest.raises(ValueError, match="end"):
        repository.scheduled_events(end=datetime(2026, 8, 7, 15))


def test_trading_repository_promotion_metrics_use_full_trace_metadata() -> None:
    # Keep this test independent of the wall clock. 18:00 UTC maps to New York
    # continuation in both standard and daylight time and is intentionally outside
    # the London-fix/rollover execution blackouts. Tomorrow guarantees the synthetic
    # quote occurs after the fixture's point-in-time fundamental snapshots.
    anchor = (datetime.now(UTC) + timedelta(days=1)).replace(
        hour=18, minute=0, second=0, microsecond=0
    )
    market = SyntheticMarketData(seed=33, direction="long", anchor=anchor)
    repository = TradingRepository(":memory:")
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
        mode=OperatingMode.PAPER,
        enable_paper_orders=True,
    )
    trace = engine.evaluate("EUR_USD", execute=True)
    assert trace.order is not None
    repository.set_halt("test-halt", "coverage")
    metrics = repository.promotion_metrics()
    assert metrics.decisions == 1
    assert metrics.trade_candidates == 1
    assert metrics.submitted_orders == 1
    assert metrics.instruments_traded == 1
    assert metrics.sessions_traded >= 1
    assert metrics.active_days == 1
    assert metrics.unresolved_halts == 1
