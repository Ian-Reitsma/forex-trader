from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from uuid import uuid4

from forex_trader.application.ports import DecisionRepository, MarketDataProvider, PaperBroker
from forex_trader.domain.costs import SessionCostModel
from forex_trader.domain.enums import DecisionDisposition, Direction, OperatingMode, OrderStatus, RiskDisposition
from forex_trader.domain.fundamentals import FundamentalBook
from forex_trader.domain.macro_history import MacroObservation
from forex_trader.domain.models import DecisionTrace, OrderRequest, jsonable
from forex_trader.domain.promotion import PracticePromotionPolicy
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
        cost_model: SessionCostModel | None = None,
        promotion_policy: PracticePromotionPolicy | None = None,
    ) -> None:
        self.market_data = market_data
        self.broker = broker
        self.repository = repository
        self.fundamentals = fundamentals
        self.fusion_policy = fusion_policy
        self.risk_policy = risk_policy
        self.mode = mode
        self.enable_paper_orders = enable_paper_orders
        self.cost_model = cost_model or SessionCostModel(minimum_samples=30)
        self.promotion_policy = promotion_policy or PracticePromotionPolicy()

    def evaluate(self, instrument: str, *, execute: bool = False) -> DecisionTrace:
        instrument = instrument.upper()
        lower = self.market_data.candles(instrument, "M5", 200)
        higher = self.market_data.candles(instrument, "H1", 200)
        quote = self.market_data.quote(instrument)
        quote_sample = self.cost_model.record_quote(quote)
        self._save_cost_sample(quote_sample)
        technical = assess_technicals(instrument, lower, higher)
        fundamental = self.fundamentals.assess_pair(instrument, as_of=quote.time)
        spread_limit = self.cost_model.spread_limit(
            instrument,
            quote.time,
            configured_maximum=self.fusion_policy.maximum_spread_pips,
        )
        candidate = self.fusion_policy.evaluate(
            technical,
            fundamental,
            quote,
            maximum_spread_pips=spread_limit,
        )
        risk = None
        order = None

        if candidate.disposition is DecisionDisposition.TRADE:
            account = self.broker.account()
            positions = self.broker.positions()
            if any(position.instrument.upper() == instrument and position.net_units != 0 for position in positions):
                risk = self.risk_policy.deny(candidate, "an open position already exists for this instrument")
            else:
                risk = self.risk_policy.authorize(
                    candidate,
                    account,
                    quote,
                    positions=positions,
                    conversion_rate=self.broker.conversion_rate,
                    mark_price=self._mark_price,
                )

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
                    assert candidate.entry_price is not None
                    signed_units = risk.units if candidate.direction is Direction.LONG else -risk.units
                    client_order_id = f"ft-{uuid4().hex[:20]}"
                    try:
                        order = self.broker.place_market_order(
                            OrderRequest(
                                client_order_id=client_order_id,
                                instrument=instrument,
                                direction=candidate.direction,
                                units=signed_units,
                                stop_loss=candidate.stop_loss,
                                take_profit=candidate.take_profit,
                                execution_key=candidate.execution_key,
                            )
                        )
                    except Exception:
                        # A raised exception means the broker adapter has classified the
                        # request as safely unsent. Ambiguous writes must return UNKNOWN.
                        self.repository.release_execution(candidate.execution_key)
                        raise

                    if order.status is OrderStatus.UNKNOWN:
                        try:
                            reconciled = self.broker.reconcile_order(
                                client_order_id=client_order_id,
                                instrument=instrument,
                                units=signed_units,
                            )
                        except RuntimeError:
                            reconciled = None
                        if reconciled is not None:
                            order = reconciled
                    if order.status is OrderStatus.REJECTED:
                        self.repository.release_execution(candidate.execution_key)
                    if order.fill_price is not None:
                        slippage = self.cost_model.record_slippage(
                            instrument=instrument,
                            observed_at=order.created_at,
                            intended_price=candidate.entry_price,
                            fill_price=order.fill_price,
                        )
                        self._save_cost_sample(slippage)

        trace = DecisionTrace.create(instrument, candidate, quote, risk, order)
        self.repository.save_trace(trace)
        return trace

    def ingest_release(
        self,
        *,
        currency: str,
        category: str,
        actual: Decimal,
        forecast: Decimal,
        previous: Decimal,
        higher_is_positive: bool = True,
        importance: Decimal = Decimal("1"),
        observed_at: datetime | None = None,
        source: str = "manual",
    ) -> object:
        available_at = observed_at or datetime.now(UTC)
        observation = MacroObservation.release(
            currency=currency,
            category=category,
            actual=actual,
            forecast=forecast,
            previous=previous,
            higher_is_positive=higher_is_positive,
            importance=importance,
            available_at=available_at,
            source=source,
        )
        if hasattr(self.repository, "save_macro_observation"):
            self.repository.save_macro_observation(observation)  # type: ignore[attr-defined]
        return self.fundamentals.apply_release(
            currency=currency,
            category=category,
            actual=actual,
            forecast=forecast,
            previous=previous,
            higher_is_positive=higher_is_positive,
            importance=importance,
            observed_at=available_at,
        )

    def ingest_news(
        self,
        *,
        currency: str,
        headline: str,
        body: str = "",
        source_weight: Decimal = Decimal("0.7"),
        observed_at: datetime | None = None,
        source: str = "manual",
    ) -> object:
        available_at = observed_at or datetime.now(UTC)
        observation = MacroObservation.news(
            currency=currency,
            headline=headline,
            body=body,
            source_weight=source_weight,
            available_at=available_at,
            source=source,
        )
        if hasattr(self.repository, "save_macro_observation"):
            self.repository.save_macro_observation(observation)  # type: ignore[attr-defined]
        return self.fundamentals.apply_news(
            currency=currency,
            headline=headline,
            body=body,
            source_weight=source_weight,
            observed_at=available_at,
        )


    def ingest_central_bank(
        self,
        *,
        currency: str,
        headline: str,
        body: str = "",
        source_weight: Decimal = Decimal("0.9"),
        observed_at: datetime | None = None,
        source: str = "official-central-bank",
    ) -> object:
        from forex_trader.domain.macro_history import MacroObservationKind

        available_at = observed_at or datetime.now(UTC)
        observation = MacroObservation.news(
            currency=currency,
            headline=headline,
            body=body,
            source_weight=source_weight,
            available_at=available_at,
            source=source,
            kind=MacroObservationKind.CENTRAL_BANK,
        )
        if hasattr(self.repository, "save_macro_observation"):
            self.repository.save_macro_observation(observation)  # type: ignore[attr-defined]
        return self.fundamentals.apply_news(
            currency=currency,
            headline=headline,
            body=body,
            source_weight=source_weight,
            observed_at=available_at,
        )

    def promotion_status(self) -> dict[str, object]:
        if not hasattr(self.repository, "promotion_metrics"):
            return {"ready": False, "reasons": ["repository does not expose promotion metrics"]}
        metrics = self.repository.promotion_metrics()  # type: ignore[attr-defined]
        return jsonable(self.promotion_policy.evaluate(metrics))

    def status(self) -> dict[str, object]:
        return {
            "mode": self.mode.value,
            "paper_orders_enabled": self.enable_paper_orders,
            "fundamental_currencies": [item.currency for item in self.fundamentals.snapshots()],
            "account": jsonable(self.broker.account()),
            "promotion": self.promotion_status(),
        }

    def _mark_price(self, instrument: str) -> Decimal | None:
        try:
            return self.market_data.quote(instrument).mid
        except Exception:
            return None

    def _save_cost_sample(self, sample: object) -> None:
        if hasattr(self.repository, "save_cost_sample"):
            self.repository.save_cost_sample(sample)  # type: ignore[attr-defined]
