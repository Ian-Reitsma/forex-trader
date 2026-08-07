from __future__ import annotations

from uuid import uuid4

from forex_trader.application.ports import DecisionRepository, MarketDataProvider, PaperBroker
from forex_trader.domain.enums import DecisionDisposition, Direction, OperatingMode, OrderStatus, RiskDisposition
from forex_trader.domain.fundamentals import FundamentalBook
from forex_trader.domain.models import DecisionTrace, OrderRequest, jsonable
from forex_trader.domain.risk import RiskPolicy
from forex_trader.domain.strategy import SignalFusionPolicy
from forex_trader.domain.technicals import assess_technicals


class TradingEngine:
    def __init__(
        self,
        *,
        market_data: MarketDataProvider,
        broker: PaperBroker,
        repository: DecisionRepository,
        fundamentals: FundamentalBook,
        fusion_policy: SignalFusionPolicy,
        risk_policy: RiskPolicy,
        mode: OperatingMode,
        enable_paper_orders: bool = False,
    ) -> None:
        self.market_data = market_data
        self.broker = broker
        self.repository = repository
        self.fundamentals = fundamentals
        self.fusion_policy = fusion_policy
        self.risk_policy = risk_policy
        self.mode = mode
        self.enable_paper_orders = enable_paper_orders

    def evaluate(self, instrument: str, *, execute: bool = False) -> DecisionTrace:
        instrument = instrument.upper()
        lower = self.market_data.candles(instrument, "M5", 200)
        higher = self.market_data.candles(instrument, "H1", 200)
        quote = self.market_data.quote(instrument)
        technical = assess_technicals(instrument, lower, higher)
        fundamental = self.fundamentals.assess_pair(instrument, as_of=quote.time)
        candidate = self.fusion_policy.evaluate(technical, fundamental, quote)
        risk = None
        order = None

        if candidate.disposition is DecisionDisposition.TRADE:
            account = self.broker.account()
            if self.broker.has_open_position(instrument):
                risk = self.risk_policy.deny(candidate, "an open position already exists for this instrument")
            else:
                risk = self.risk_policy.authorize(candidate, account, quote)

            should_execute = (
                execute
                and self.mode is OperatingMode.PAPER
                and self.enable_paper_orders
                and risk.disposition is RiskDisposition.GRANTED
            )
            if should_execute:
                if not self.repository.claim_execution(candidate.execution_key):
                    risk = self.risk_policy.deny(candidate, "this signal candle was already submitted")
                else:
                    assert candidate.stop_loss is not None
                    assert candidate.take_profit is not None
                    signed_units = risk.units if candidate.direction is Direction.LONG else -risk.units
                    try:
                        order = self.broker.place_market_order(
                            OrderRequest(
                                client_order_id=f"ft-{uuid4().hex[:20]}",
                                instrument=instrument,
                                direction=candidate.direction,
                                units=signed_units,
                                stop_loss=candidate.stop_loss,
                                take_profit=candidate.take_profit,
                                execution_key=candidate.execution_key,
                            )
                        )
                    except Exception:
                        self.repository.release_execution(candidate.execution_key)
                        raise
                    if order.status is OrderStatus.REJECTED:
                        self.repository.release_execution(candidate.execution_key)

        trace = DecisionTrace.create(instrument, candidate, quote, risk, order)
        self.repository.save_trace(trace)
        return trace

    def status(self) -> dict[str, object]:
        return {
            "mode": self.mode.value,
            "paper_orders_enabled": self.enable_paper_orders,
            "fundamental_currencies": [item.currency for item in self.fundamentals.snapshots()],
            "account": jsonable(self.broker.account()),
        }
