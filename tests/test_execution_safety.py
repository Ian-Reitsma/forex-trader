from datetime import timedelta
from decimal import Decimal

from forex_trader.adapters.simulator import SimulatedPaperBroker
from forex_trader.application.engine import TradingEngine
from forex_trader.domain.enums import DecisionDisposition, OperatingMode, OrderStatus, RiskDisposition
from forex_trader.domain.events import ScheduledMacroEvent
from forex_trader.domain.models import AccountSnapshot, Quote
from forex_trader.domain.risk import RiskPolicy
from forex_trader.domain.strategy import SignalFusionPolicy
from forex_trader.infrastructure.trading_repository import TradingRepository


def build_engine(market, fundamentals, broker, repository):  # type: ignore[no-untyped-def]
    return TradingEngine(
        market_data=market,
        broker=broker,
        repository=repository,
        fundamentals=fundamentals,
        fusion_policy=SignalFusionPolicy(minimum_score=Decimal("0.5")),
        risk_policy=RiskPolicy(),
        mode=OperatingMode.PAPER,
        enable_paper_orders=True,
    )


def test_high_impact_event_blackout_blocks_an_otherwise_valid_setup(market, fundamentals) -> None:  # type: ignore[no-untyped-def]
    repository = TradingRepository(":memory:")
    broker = SimulatedPaperBroker(market)
    engine = build_engine(market, fundamentals, broker, repository)
    quote = market.quote("EUR_USD")
    repository.save_scheduled_event(
        ScheduledMacroEvent.create(
            currency="USD",
            scheduled_at=quote.time + timedelta(minutes=5),
            name="Payrolls",
            pre_blackout=timedelta(minutes=15),
            post_blackout=timedelta(minutes=5),
        )
    )
    trace = engine.evaluate("EUR_USD", execute=True)
    assert trace.candidate.disposition is DecisionDisposition.ABSTAIN
    assert trace.candidate.rejection_code == "EVENT_BLACKOUT"
    assert trace.order is None


def test_existing_account_execution_lock_blocks_concurrent_write(market, fundamentals) -> None:  # type: ignore[no-untyped-def]
    repository = TradingRepository(":memory:")
    broker = SimulatedPaperBroker(market)
    engine = build_engine(market, fundamentals, broker, repository)
    assert repository.acquire_account_lock("SIM-001", "other-owner", ttl_seconds=60)
    trace = engine.evaluate("EUR_USD", execute=True)
    assert trace.order is None
    assert trace.risk is not None and trace.risk.disposition is RiskDisposition.DENIED
    assert "execution is in progress" in trace.risk.reasons[0]


def test_missing_protection_attempts_emergency_close_and_latches_halt(market, fundamentals) -> None:  # type: ignore[no-untyped-def]
    class UnprotectedBroker(SimulatedPaperBroker):
        def ensure_trade_protection(self, trade_id, *, stop_loss, take_profit):  # type: ignore[no-untyped-def]
            return False

    repository = TradingRepository(":memory:")
    broker = UnprotectedBroker(market)
    engine = build_engine(market, fundamentals, broker, repository)
    trace = engine.evaluate("EUR_USD", execute=True)
    assert trace.order is not None
    assert trace.order.status is OrderStatus.EMERGENCY_CLOSE
    assert repository.get_halt("execution:SIM-001") is not None
    assert broker.has_open_position("EUR_USD") is False


def test_deterministic_broker_exception_is_audited_as_rejected_and_claim_released(market, fundamentals) -> None:  # type: ignore[no-untyped-def]
    class RejectingBroker(SimulatedPaperBroker):
        def place_market_order(self, request):  # type: ignore[no-untyped-def]
            raise ValueError("deterministic order validation error")

        def positions(self):  # type: ignore[no-untyped-def]
            return []

    repository = TradingRepository(":memory:")
    broker = RejectingBroker(market)
    engine = build_engine(market, fundamentals, broker, repository)
    first = engine.evaluate("EUR_USD", execute=True)
    second = engine.evaluate("EUR_USD", execute=True)
    assert first.order is not None and first.order.status is OrderStatus.REJECTED
    assert second.order is not None and second.order.status is OrderStatus.REJECTED
    assert "ValueError" in first.order.raw["error"]


def test_send_time_price_move_can_invalidate_trade_before_submission(market, fundamentals) -> None:  # type: ignore[no-untyped-def]
    class MovingBroker(SimulatedPaperBroker):
        def quote_for_units(self, instrument: str, units: int | None) -> Quote:
            base = market.quote(instrument)
            # Move executable price far enough to consume the structural target.
            return Quote(
                instrument,
                base.bid + Decimal("0.0100"),
                base.ask + Decimal("0.0100"),
                base.time + timedelta(seconds=1),
                bid_liquidity=Decimal("1000000"),
                ask_liquidity=Decimal("1000000"),
            )

    repository = TradingRepository(":memory:")
    broker = MovingBroker(market)
    engine = build_engine(market, fundamentals, broker, repository)
    trace = engine.evaluate("EUR_USD", execute=True)
    assert trace.order is None
    assert trace.risk is not None and trace.risk.disposition is RiskDisposition.DENIED
    assert trace.candidate.rejection_code in {"LATE_ENTRY", "INSUFFICIENT_NET_REWARD"}


def test_latched_marked_loss_detected_on_execution_refresh(market, fundamentals) -> None:  # type: ignore[no-untyped-def]
    class DeterioratingAccountBroker(SimulatedPaperBroker):
        def __init__(self, market_data):  # type: ignore[no-untyped-def]
            super().__init__(market_data)
            self.calls = 0

        def account(self) -> AccountSnapshot:
            self.calls += 1
            if self.calls == 1:
                return super().account()
            base = super().account()
            return AccountSnapshot(
                base.account_id,
                base.currency,
                base.balance,
                base.nav,
                margin_available=base.margin_available,
                unrealized_pl=Decimal("-1500"),
                open_position_count=0,
            )

    repository = TradingRepository(":memory:")
    broker = DeterioratingAccountBroker(market)
    engine = build_engine(market, fundamentals, broker, repository)
    trace = engine.evaluate("EUR_USD", execute=True)
    assert trace.order is None
    assert trace.risk is not None and trace.risk.disposition is RiskDisposition.DENIED
    assert repository.get_halt("risk:SIM-001") is not None
