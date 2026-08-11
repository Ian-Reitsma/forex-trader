from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import uuid4

from forex_trader.application.ports import DecisionRepository, MarketDataProvider, PaperBroker
from forex_trader.application.readiness import assess_engine_readiness
from forex_trader.domain.costs import SessionCostModel
from forex_trader.domain.enums import DecisionDisposition, Direction, OperatingMode, OrderStatus, RiskDisposition
from forex_trader.domain.events import EventImportance, ScheduledMacroEvent, pair_event_blackout
from forex_trader.domain.fundamentals import FundamentalBook
from forex_trader.domain.instruments import pip_size_for, register_spec
from forex_trader.domain.macro_history import MacroObservation, MacroObservationKind, PointInTimeFundamentalBook
from forex_trader.domain.models import (
    AccountSnapshot,
    DecisionTrace,
    InstrumentSpec,
    OrderRequest,
    OrderResult,
    Quote,
    RiskAuthorization,
    TradeCandidate,
    jsonable,
)
from forex_trader.domain.portfolio import OpenPosition
from forex_trader.domain.promotion import PracticePromotionPolicy
from forex_trader.domain.risk import RiskPolicy
from forex_trader.domain.sessions import SessionPhase, classify_phase
from forex_trader.domain.strategy import SignalFusionPolicy
from forex_trader.domain.technicals import assess_technicals


class TradingEngine:
    def __init__(
        self,
        *,
        market_data: MarketDataProvider,
        broker: PaperBroker,
        repository: DecisionRepository,
        fundamentals: FundamentalBook | PointInTimeFundamentalBook,
        fusion_policy: SignalFusionPolicy,
        risk_policy: RiskPolicy,
        mode: OperatingMode,
        enable_paper_orders: bool = False,
        cost_model: SessionCostModel | None = None,
        promotion_policy: PracticePromotionPolicy | None = None,
        maximum_slippage_pips: Decimal = Decimal("0.5"),
    ) -> None:
        if maximum_slippage_pips <= 0:
            raise ValueError("maximum_slippage_pips must be positive")
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
        self.maximum_slippage_pips = maximum_slippage_pips

    def evaluate(self, instrument: str, *, execute: bool = False) -> DecisionTrace:
        instrument = instrument.upper()
        spec = self._instrument_spec(instrument)
        lower = self.market_data.candles(instrument, "M5", 200)
        higher = self.market_data.candles(instrument, "H1", 200)
        quote = self.market_data.quote(instrument)
        quote_sample = self.cost_model.record_quote(quote, event_risk=self._event_risk(instrument, quote.time))
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
        candidate = self._apply_context_hard_gates(candidate, quote)
        risk = None
        order = None
        trace_quote = quote
        account_snapshot = None
        positions_snapshot: list[OpenPosition] = []

        if candidate.disposition is DecisionDisposition.TRADE:
            account_snapshot = self.broker.account()
            positions_snapshot = list(self.broker.positions())
            halt_reason = self._account_halt_reason(account_snapshot.account_id)
            if halt_reason:
                risk = self.risk_policy.deny(candidate, f"account is halted: {halt_reason}", account_id=account_snapshot.account_id)
            elif any(position.instrument.upper() == instrument and position.net_units != 0 for position in positions_snapshot):
                risk = self.risk_policy.deny(candidate, "an open position already exists for this instrument", account_id=account_snapshot.account_id)
            else:
                risk = self.risk_policy.authorize(
                    candidate,
                    account_snapshot,
                    quote,
                    positions=positions_snapshot,
                    conversion_rate=self.broker.conversion_rate,
                    mark_price=self._mark_price,
                    margin_rate=getattr(spec, "margin_rate", None),
                    maximum_position_units=getattr(spec, "maximum_position_size", None),
                )

            should_execute = (
                execute
                and self.mode is OperatingMode.PAPER
                and self.enable_paper_orders
                and risk.disposition is RiskDisposition.GRANTED
            )
            if should_execute:
                candidate, risk, order, trace_quote, account_snapshot, positions_snapshot = self._execute_candidate(
                    candidate=candidate,
                    initial_risk=risk,
                    initial_account=account_snapshot,
                    spec=spec,
                    spread_limit=spread_limit,
                )

        trace = DecisionTrace.create(
            instrument,
            candidate,
            trace_quote,
            risk,
            order,
            metadata={
                "strategy_policy": "zone-liquidity-structure-v0.5",
                "risk_policy": "practice-risk-v0.5",
                "session_phase": classify_phase(trace_quote.time).value,
                "instrument_spec": jsonable(spec) if spec is not None else None,
                "account_snapshot": jsonable(account_snapshot) if account_snapshot is not None else None,
                "positions_snapshot": jsonable(positions_snapshot),
            },
        )
        self.repository.save_trace(trace)
        return trace

    def _execute_candidate(
        self,
        *,
        candidate: TradeCandidate,
        initial_risk: RiskAuthorization,
        initial_account: AccountSnapshot,
        spec: InstrumentSpec | None,
        spread_limit: Decimal,
    ) -> tuple[
        TradeCandidate,
        RiskAuthorization,
        OrderResult | None,
        Quote,
        AccountSnapshot,
        list[OpenPosition],
    ]:
        account_id = initial_account.account_id
        lock_owner = f"exec-{uuid4().hex}"
        acquired = self._acquire_account_lock(account_id, lock_owner)
        if not acquired:
            denied = self.risk_policy.deny(candidate, "another account execution is in progress", account_id=account_id)
            return candidate, denied, None, self.market_data.quote(candidate.instrument), initial_account, list(self.broker.positions())

        try:
            halt_reason = self._account_halt_reason(account_id)
            if halt_reason:
                denied = self.risk_policy.deny(candidate, f"account is halted: {halt_reason}", account_id=account_id)
                return candidate, denied, None, self.market_data.quote(candidate.instrument), initial_account, list(self.broker.positions())

            readiness_reason = self._execution_readiness_reason(candidate.instrument)
            if readiness_reason is not None:
                denied = self.risk_policy.deny(candidate, readiness_reason, account_id=account_id)
                return (
                    candidate,
                    denied,
                    None,
                    self.market_data.quote(candidate.instrument),
                    initial_account,
                    list(self.broker.positions()),
                )

            account = self.broker.account()
            positions = list(self.broker.positions())
            capital_base = min(account.balance, account.nav)
            if self._observe_latched_loss(account, candidate.signal_time, capital_base):
                reason = "latched daily marked-loss limit reached"
                self._set_halt(f"risk:{account_id}", reason)
                denied = self.risk_policy.deny(candidate, reason, account_id=account_id)
                return candidate, denied, None, self.market_data.quote(candidate.instrument), account, positions
            if any(position.instrument.upper() == candidate.instrument.upper() and position.net_units != 0 for position in positions):
                denied = self.risk_policy.deny(candidate, "an open position already exists for this instrument", account_id=account_id)
                return candidate, denied, None, self.market_data.quote(candidate.instrument), account, positions

            # Reprice with executable depth for the proposed size. This catches both
            # stale quotes and orders larger than the current top-of-book liquidity.
            fresh_quote = self._quote_for_units(candidate.instrument, initial_risk.units)
            fresh_sample = self.cost_model.record_quote(fresh_quote, event_risk=self._event_risk(candidate.instrument, fresh_quote.time))
            self._save_cost_sample(fresh_sample)
            candidate = self.fusion_policy.revalidate_execution(
                candidate,
                fresh_quote,
                maximum_spread_pips=self.cost_model.spread_limit(
                    candidate.instrument,
                    fresh_quote.time,
                    configured_maximum=spread_limit,
                ),
            )
            candidate = self._apply_context_hard_gates(candidate, fresh_quote)
            if candidate.disposition is not DecisionDisposition.TRADE:
                denied = self.risk_policy.deny(candidate, candidate.rejection_code or "send-time execution gate failed", account_id=account_id)
                return candidate, denied, None, fresh_quote, account, positions

            risk = self.risk_policy.authorize(
                candidate,
                account,
                fresh_quote,
                positions=positions,
                conversion_rate=self.broker.conversion_rate,
                mark_price=self._mark_price,
                margin_rate=getattr(spec, "margin_rate", None),
                maximum_position_units=getattr(spec, "maximum_position_size", None),
            )
            if risk.disposition is not RiskDisposition.GRANTED:
                return candidate, risk, None, fresh_quote, account, positions

            # The final size can differ after the fresh account/price snapshot. Ask
            # for executable pricing once more at precisely the authorized size.
            size_quote = self._quote_for_units(candidate.instrument, risk.units)
            if size_quote != fresh_quote:
                candidate = self.fusion_policy.revalidate_execution(
                    candidate,
                    size_quote,
                    maximum_spread_pips=self.cost_model.spread_limit(
                        candidate.instrument,
                        size_quote.time,
                        configured_maximum=spread_limit,
                    ),
                )
                if candidate.disposition is not DecisionDisposition.TRADE:
                    denied = self.risk_policy.deny(candidate, candidate.rejection_code or "size-aware execution gate failed", account_id=account_id)
                    return candidate, denied, None, size_quote, account, positions
                risk = self.risk_policy.authorize(
                    candidate,
                    account,
                    size_quote,
                    positions=positions,
                    conversion_rate=self.broker.conversion_rate,
                    mark_price=self._mark_price,
                    margin_rate=getattr(spec, "margin_rate", None),
                    maximum_position_units=getattr(spec, "maximum_position_size", None),
                )
                fresh_quote = size_quote
            if risk.disposition is not RiskDisposition.GRANTED or risk.expired:
                denied = risk if risk.disposition is RiskDisposition.DENIED else self.risk_policy.deny(candidate, "risk authorization expired before broker submission", account_id=account_id)
                return candidate, denied, None, fresh_quote, account, positions

            if not self.repository.claim_execution(candidate.execution_key):
                denied = self.risk_policy.deny(candidate, "this setup/location signal was already submitted", account_id=account_id)
                return candidate, denied, None, fresh_quote, account, positions

            assert candidate.stop_loss is not None and candidate.take_profit is not None and candidate.entry_price is not None
            signed_units = risk.units if candidate.direction is Direction.LONG else -risk.units
            allowance = self.cost_model.slippage_allowance(
                candidate.instrument,
                fresh_quote.time,
                configured_maximum=self.maximum_slippage_pips,
            )
            pip = pip_size_for(candidate.instrument)
            price_bound = candidate.entry_price + pip * allowance if candidate.direction is Direction.LONG else candidate.entry_price - pip * allowance
            client_order_id = f"ft-{uuid4().hex[:20]}"
            try:
                order = self.broker.place_market_order(
                    OrderRequest(
                        client_order_id=client_order_id,
                        instrument=candidate.instrument,
                        direction=candidate.direction,
                        units=signed_units,
                        stop_loss=candidate.stop_loss,
                        take_profit=candidate.take_profit,
                        execution_key=candidate.execution_key,
                        intended_price=candidate.entry_price,
                        price_bound=price_bound,
                        authorization_id=str(risk.authorization_id),
                    )
                )
            except Exception as exc:
                # The adapter is required to return UNKNOWN for ambiguous writes. Any
                # raised exception is therefore classified as safely rejected/unsent,
                # persisted in the trace, and the claim is released for a later setup.
                self.repository.release_execution(candidate.execution_key)
                order = OrderResult(
                    client_order_id=client_order_id,
                    provider_order_id=None,
                    status=OrderStatus.REJECTED,
                    instrument=candidate.instrument,
                    units=signed_units,
                    fill_price=None,
                    raw={"error": f"{type(exc).__name__}: {str(exc)[:240]}"},
                )
                return candidate, risk, order, fresh_quote, account, positions

            if order.status is OrderStatus.UNKNOWN:
                try:
                    reconciled = self.broker.reconcile_order(
                        client_order_id=client_order_id,
                        instrument=candidate.instrument,
                        units=signed_units,
                    )
                except RuntimeError:
                    reconciled = None
                if reconciled is not None:
                    order = reconciled
                if order.status in {OrderStatus.UNKNOWN, OrderStatus.CREATED, OrderStatus.ACKNOWLEDGED, OrderStatus.RECONCILIATION_REQUIRED}:
                    self._set_halt(
                        f"execution:{account_id}",
                        f"unresolved broker write {client_order_id}; reconcile account before new risk",
                    )
            if order.status in {OrderStatus.REJECTED, OrderStatus.CANCELLED}:
                self.repository.release_execution(candidate.execution_key)

            if order.status is OrderStatus.FILLED:
                order = self._confirm_protection(order, candidate, account_id)

            if order.fill_price is not None:
                slippage = self.cost_model.record_slippage(
                    instrument=candidate.instrument,
                    observed_at=order.broker_time or order.created_at,
                    intended_price=candidate.entry_price,
                    fill_price=order.fill_price,
                    direction=candidate.direction.value,
                    event_risk=self._event_risk(candidate.instrument, order.broker_time or order.created_at),
                )
                self._save_cost_sample(slippage)
            return candidate, risk, order, fresh_quote, account, positions
        finally:
            self._release_account_lock(account_id, lock_owner)

    def _confirm_protection(
        self,
        order: OrderResult,
        candidate: TradeCandidate,
        account_id: str,
    ) -> OrderResult:
        if order.provider_trade_id is None:
            self._set_halt(f"execution:{account_id}", "filled broker order did not expose a trade ID for protection verification")
            return replace(order, status=OrderStatus.RECONCILIATION_REQUIRED)
        ensure = getattr(self.broker, "ensure_trade_protection", None)
        if ensure is None:
            self._set_halt(f"execution:{account_id}", "broker adapter cannot verify dependent stop/target protection")
            return replace(order, status=OrderStatus.RECONCILIATION_REQUIRED)
        try:
            protected = bool(
                ensure(
                    order.provider_trade_id,
                    stop_loss=candidate.stop_loss,
                    take_profit=candidate.take_profit,
                )
            )
        except Exception:
            protected = False
        if protected:
            return replace(order, status=OrderStatus.PROTECTED, protection_confirmed=True)

        close = getattr(self.broker, "close_trade", None)
        close_result: object = None
        if close is not None:
            try:
                close_result = close(order.provider_trade_id)
            except Exception as exc:
                close_result = {"error": f"{type(exc).__name__}: {str(exc)[:200]}"}
        self._set_halt(
            f"execution:{account_id}",
            f"protection could not be verified for trade {order.provider_trade_id}; emergency close attempted",
        )
        return replace(
            order,
            status=OrderStatus.EMERGENCY_CLOSE,
            raw={**order.raw, "emergency_close": jsonable(close_result)},
        )

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
        self._persist_observation(observation)
        return self._append_or_apply(observation)

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
        self._persist_observation(observation)
        return self._append_or_apply(observation)

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
        self._persist_observation(observation)
        return self._append_or_apply(observation)

    def ingest_scheduled_event(
        self,
        *,
        currency: str,
        scheduled_at: datetime,
        name: str,
        importance: str = "high",
        source: str = "manual",
        pre_blackout_minutes: int = 15,
        post_blackout_minutes: int = 5,
    ) -> ScheduledMacroEvent:
        event = ScheduledMacroEvent.create(
            currency=currency,
            scheduled_at=scheduled_at,
            name=name,
            importance=EventImportance(importance.lower()),
            source=source,
            pre_blackout=timedelta(minutes=pre_blackout_minutes),
            post_blackout=timedelta(minutes=post_blackout_minutes),
        )
        saver = getattr(self.repository, "save_scheduled_event", None)
        if saver is None:
            raise RuntimeError("repository does not support scheduled macro events")
        saver(event)
        return event

    def instrument_universe(self) -> tuple[str, ...]:
        provider = self.broker
        discover = getattr(provider, "currency_instruments", None)
        if discover is None:
            return ()
        return tuple(spec.name for spec in discover())

    def clear_halt(self, name: str) -> None:
        clearer = getattr(self.repository, "clear_halt", None)
        if clearer is None:
            raise RuntimeError("repository does not support persistent halts")
        clearer(name)

    def promotion_status(self) -> dict[str, object]:
        metrics_reader = getattr(self.repository, "promotion_metrics", None)
        if metrics_reader is None:
            return {"ready": False, "reasons": ["repository does not expose promotion metrics"]}
        metrics = metrics_reader()
        result = jsonable(self.promotion_policy.evaluate(metrics))
        if not isinstance(result, dict):
            raise TypeError("promotion evaluation must serialize to a mapping")
        return {str(key): value for key, value in result.items()}

    def runtime_status(self) -> dict[str, object]:
        getter = getattr(self.repository, "runtime_state", None)
        if getter is None:
            return {
                "active": False,
                "healthy": False,
                "stale": True,
                "reason": "repository does not expose autonomous runtime heartbeat state",
            }
        raw = getter("autonomous_practice")
        if not isinstance(raw, dict):
            return {
                "active": False,
                "healthy": False,
                "stale": True,
                "reason": "no autonomous Practice runtime heartbeat has been recorded",
            }
        payload: dict[str, object] = {str(key): value for key, value in raw.items()}
        heartbeat_raw = payload.get("heartbeat_at")
        try:
            heartbeat = datetime.fromisoformat(str(heartbeat_raw)).astimezone(UTC)
        except (TypeError, ValueError):
            heartbeat = None
        raw_interval = payload.get("interval_seconds", 300.0)
        if isinstance(raw_interval, (int, float, str)):
            try:
                interval_seconds = float(raw_interval)
            except ValueError:
                interval_seconds = 300.0
        else:
            interval_seconds = 300.0
        stale_after = max(900.0, max(0.0, interval_seconds) * 3.0)
        age_seconds = (
            None
            if heartbeat is None
            else max(0.0, (datetime.now(UTC) - heartbeat).total_seconds())
        )
        stale = age_seconds is None or age_seconds > stale_after
        active = bool(payload.get("active"))
        declared = str(payload.get("status") or "unknown")
        healthy = active and not stale and declared in {"starting", "running"}
        if not active:
            reason = "autonomous Practice runtime is not active"
        elif stale:
            reason = "autonomous Practice runtime heartbeat is stale"
        elif declared not in {"starting", "running"}:
            reason = f"autonomous Practice runtime reports {declared}"
        else:
            reason = "autonomous Practice runtime heartbeat is healthy"
        payload.update(
            {
                "active": active,
                "healthy": healthy,
                "stale": stale,
                "heartbeat_age_seconds": age_seconds,
                "stale_after_seconds": stale_after,
                "reason": reason,
            }
        )
        return payload

    def status(self) -> dict[str, object]:
        account = self.broker.account()
        return {
            "mode": self.mode.value,
            "paper_orders_enabled": self.enable_paper_orders,
            "fundamental_currencies": [item.currency for item in self.fundamentals.snapshots()],
            "account": jsonable(account),
            "execution_halt": self._account_halt_reason(account.account_id),
            "runtime": self.runtime_status(),
            "promotion": self.promotion_status(),
        }

    def _append_or_apply(self, observation: MacroObservation) -> object:
        if isinstance(self.fundamentals, PointInTimeFundamentalBook):
            self.fundamentals.append(observation)
            return self.fundamentals.get(observation.currency, as_of=datetime.now(UTC)) or object()
        if observation.kind is MacroObservationKind.RELEASE:
            assert observation.actual is not None and observation.forecast is not None and observation.previous is not None
            return self.fundamentals.apply_release(
                currency=observation.currency,
                category=observation.category,
                actual=observation.actual,
                forecast=observation.forecast,
                previous=observation.previous,
                higher_is_positive=observation.higher_is_positive,
                importance=observation.importance,
                observed_at=observation.available_at,
            )
        if observation.kind is MacroObservationKind.CENTRAL_BANK:
            return self.fundamentals.apply_central_bank(
                currency=observation.currency,
                headline=observation.headline,
                body=observation.body,
                source_weight=observation.source_weight,
                observed_at=observation.available_at,
            )
        return self.fundamentals.apply_news(
            currency=observation.currency,
            headline=observation.headline,
            body=observation.body,
            source_weight=observation.source_weight,
            observed_at=observation.available_at,
        )

    def _persist_observation(self, observation: MacroObservation) -> None:
        saver = getattr(self.repository, "save_macro_observation", None)
        if saver is not None:
            saver(observation)

    def _apply_context_hard_gates(
        self,
        candidate: TradeCandidate,
        quote: Quote,
    ) -> TradeCandidate:
        if candidate.disposition is not DecisionDisposition.TRADE:
            return candidate
        blocked, reasons = pair_event_blackout(candidate.instrument, quote.time, self._scheduled_events_near(quote.time))
        if blocked:
            return replace(
                candidate,
                disposition=DecisionDisposition.ABSTAIN,
                rejection_code="EVENT_BLACKOUT",
                entry_price=None,
                stop_loss=None,
                take_profit=None,
                reasons=(*candidate.reasons, *(f"EVENT_BLACKOUT: {reason}" for reason in reasons)),
            )
        phase = classify_phase(quote.time)
        if phase is SessionPhase.ROLLOVER:
            return replace(
                candidate,
                disposition=DecisionDisposition.ABSTAIN,
                rejection_code="ROLLOVER_BLACKOUT",
                entry_price=None,
                stop_loss=None,
                take_profit=None,
                reasons=(*candidate.reasons, "ROLLOVER_BLACKOUT: New York rollover execution window"),
            )
        return candidate

    def _scheduled_events_near(self, instant: datetime) -> list[ScheduledMacroEvent]:
        getter = getattr(self.repository, "scheduled_events", None)
        if getter is None:
            return []
        return list(getter(start=instant - timedelta(hours=1), end=instant + timedelta(hours=1)))

    def _event_risk(self, instrument: str, instant: datetime) -> bool:
        return pair_event_blackout(instrument, instant, self._scheduled_events_near(instant))[0]

    def _execution_readiness_reason(self, instrument: str) -> str | None:
        if not bool(getattr(self.broker, "requires_runtime_readiness", False)):
            return None
        checker = getattr(self.repository, "execution_ready", None)
        if checker is None:
            return None
        try:
            _, _, readiness = assess_engine_readiness(self, instrument)
        except (AttributeError, RuntimeError, ValueError) as exc:
            return f"runtime readiness assessment failed: {type(exc).__name__}: {exc}"
        if readiness.ready:
            return None
        reasons = "; ".join(readiness.reasons) or "runtime data-quality readiness is false"
        return f"runtime readiness blocked execution: {reasons}"

    def _account_halt_reason(self, account_id: str) -> str | None:
        getter = getattr(self.repository, "get_halt", None)
        if getter is None:
            return None
        reason = getter("global") or getter(f"execution:{account_id}") or getter(f"risk:{account_id}")
        return None if reason is None else str(reason)

    def _set_halt(self, name: str, reason: str) -> None:
        setter = getattr(self.repository, "set_halt", None)
        if setter is not None:
            setter(name, reason)

    def _acquire_account_lock(self, account_id: str, owner: str) -> bool:
        acquire = getattr(self.repository, "acquire_account_lock", None)
        return True if acquire is None else bool(acquire(account_id, owner, ttl_seconds=30.0))

    def _release_account_lock(self, account_id: str, owner: str) -> None:
        release = getattr(self.repository, "release_account_lock", None)
        if release is not None:
            release(account_id, owner)

    def _observe_latched_loss(
        self,
        account: AccountSnapshot,
        signal_time: datetime,
        capital_base: Decimal,
    ) -> bool:
        observe = getattr(self.repository, "observe_risk_day", None)
        if observe is None or capital_base <= 0:
            return False
        marked_pl = account.realized_pl_today + account.unrealized_pl
        return bool(
            observe(
                account_id=account.account_id,
                trading_day=signal_time.astimezone(UTC).date().isoformat(),
                marked_pl=marked_pl,
                loss_limit_amount=capital_base * self.risk_policy.max_daily_loss_fraction,
            )
        )

    def _instrument_spec(self, instrument: str) -> InstrumentSpec | None:
        getter = getattr(self.broker, "instrument_spec", None)
        if getter is None:
            return None
        spec = getter(instrument)
        if not isinstance(spec, InstrumentSpec):
            raise TypeError("broker instrument_spec must return InstrumentSpec")
        register_spec(spec)
        return spec

    def _quote_for_units(self, instrument: str, units: int | None) -> Quote:
        getter = getattr(self.broker, "quote_for_units", None)
        if getter is not None:
            quote = getter(instrument, units)
            if not isinstance(quote, Quote):
                raise TypeError("broker quote_for_units must return Quote")
            return quote
        return self.market_data.quote(instrument)

    def _mark_price(self, instrument: str) -> Decimal | None:
        try:
            return self.market_data.quote(instrument).mid
        except Exception:
            return None

    def _save_cost_sample(self, sample: object) -> None:
        saver = getattr(self.repository, "save_cost_sample", None)
        if saver is not None:
            saver(sample)
