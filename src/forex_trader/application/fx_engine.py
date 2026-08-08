from __future__ import annotations

from contextlib import nullcontext
from dataclasses import replace
from datetime import datetime, timedelta
from decimal import Decimal

from forex_trader.application.engine import TradingEngine
from forex_trader.application.signal_capture import SignalEvaluationInputs
from forex_trader.domain.events import ScheduledMacroEvent, pair_event_blackout
from forex_trader.domain.models import DecisionTrace
from forex_trader.domain.risk_day import fx_risk_day_key
from forex_trader.domain.sessions import SessionPhase, classify_phase


class FxTradingEngine(TradingEngine):
    """Deployable FX engine with FX risk-day and evaluation-snapshot semantics."""

    def evaluate(self, instrument: str, *, execute: bool = False) -> DecisionTrace:
        """Evaluate one instrument inside an optional completed-candle snapshot scope.

        The market-data adapter may reuse completed candles inside this one decision. Live
        quotes, account state and broker writes are deliberately outside that cache.
        """
        scope_factory = getattr(self.market_data, "evaluation_scope", None)
        scope = scope_factory() if callable(scope_factory) else nullcontext()
        with scope:
            trace = super().evaluate(instrument, execute=execute)
        # Snapshot-boundary tests intentionally replace the base evaluation with an opaque
        # sentinel. Metadata enrichment is a DecisionTrace concern and must not change the
        # scope wrapper's behavior for non-trace return values.
        if not isinstance(trace, DecisionTrace):
            return trace
        metadata = dict(trace.metadata)
        selected_policy = trace.candidate.evidence.get("selected_policy")
        if selected_policy:
            metadata["strategy_policy"] = selected_policy
        metadata["regime"] = trace.candidate.evidence.get("regime")
        metadata["independent_confirmation_count"] = trace.candidate.evidence.get("independent_confirmation_count")
        metadata["independent_source_count"] = trace.candidate.evidence.get("independent_source_count")
        if trace.risk is not None and trace.risk.risk_policy_version:
            metadata["risk_policy"] = trace.risk.risk_policy_version
        account = metadata.get("account_snapshot")
        if isinstance(account, dict) and account.get("account_id"):
            readiness = getattr(self.repository, "execution_readiness", None)
            if readiness is not None:
                metadata["execution_readiness"] = readiness(str(account["account_id"]))
        enriched = replace(trace, metadata=metadata)
        self.repository.save_trace(enriched)
        return enriched

    def evaluate_with_signal_inputs(
        self,
        instrument: str,
        *,
        execute: bool = False,
    ) -> tuple[DecisionTrace, SignalEvaluationInputs]:
        """Evaluate once and capture the exact pre-risk signal inputs without provider rereads.

        This path is intentionally shadow-only. It opens an outer completed-candle snapshot,
        invokes the normal production evaluation inside that scope, and then reuses the
        already-cached candle responses before the scope closes. The quote comes from the
        actual trace; fundamentals and the adaptive spread ceiling are point-in-time pure
        reads at that quote timestamp. No broker write or second executable quote is allowed.
        """
        if execute:
            raise ValueError("signal input capture is restricted to shadow evaluation")
        scope_factory = getattr(self.market_data, "evaluation_scope", None)
        if not callable(scope_factory):
            raise RuntimeError("signal input capture requires evaluation-scoped market data")
        normalized = instrument.upper()
        with scope_factory():
            trace = self.evaluate(normalized, execute=False)
            if not isinstance(trace, DecisionTrace):
                raise TypeError("signal input capture requires a DecisionTrace result")
            lower = tuple(self.market_data.candles(normalized, "M5", 200))
            higher = tuple(self.market_data.candles(normalized, "H1", 200))
            quote = trace.quote
            fundamental = self.fundamentals.assess_pair(normalized, as_of=quote.time)
            spread_limit = self.cost_model.spread_limit(
                normalized,
                quote.time,
                configured_maximum=self.fusion_policy.maximum_spread_pips,
            )
            _, event_reasons = pair_event_blackout(
                normalized,
                quote.time,
                self._scheduled_events_near(quote.time),
            )
            captured = SignalEvaluationInputs(
                instrument=normalized,
                lower_candles=lower,
                higher_candles=higher,
                quote=quote,
                fundamental=fundamental,
                maximum_spread_pips=spread_limit,
                event_blackout_reasons=tuple(event_reasons),
                rollover_blackout=classify_phase(quote.time) is SessionPhase.ROLLOVER,
            )
        return trace, captured

    def _scheduled_events_near(self, instant: datetime) -> list[ScheduledMacroEvent]:
        """Merge durable/manual events with point-in-time configured calendar events.

        A configured calendar is part of the risk boundary. If its scheduled-event query
        fails, evaluation fails closed instead of treating an unavailable calendar as proof
        that no event risk exists.
        """
        events = super()._scheduled_events_near(instant)
        external_context = getattr(self.fusion_policy, "external_context", None)
        calendar = getattr(external_context, "economic_calendar", None)
        scheduled_events = getattr(calendar, "scheduled_events", None)
        if not callable(scheduled_events):
            return events
        try:
            external_events = scheduled_events(
                start=instant - timedelta(hours=1),
                end=instant + timedelta(hours=1),
                as_of=instant,
            )
        except Exception as exc:
            raise RuntimeError(
                f"configured economic calendar scheduled-event query failed: {type(exc).__name__}: {str(exc)[:200]}"
            ) from exc
        deduplicated = {event.event_id: event for event in events}
        deduplicated.update({event.event_id: event for event in external_events})
        return sorted(deduplicated.values(), key=lambda event: (event.scheduled_at, str(event.event_id)))

    def _observe_latched_loss(self, account, signal_time: datetime, capital_base: Decimal) -> bool:  # type: ignore[no-untyped-def]
        observe = getattr(self.repository, "observe_risk_day", None)
        if observe is None or capital_base <= 0:
            return False
        marked_pl = account.realized_pl_today + account.unrealized_pl
        return bool(
            observe(
                account_id=account.account_id,
                trading_day=fx_risk_day_key(signal_time),
                marked_pl=marked_pl,
                loss_limit_amount=capital_base * self.risk_policy.max_daily_loss_fraction,
            )
        )
