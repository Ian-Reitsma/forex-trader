from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Mapping, cast

from forex_trader.application.risk_breaker import RiskBreakerRepository, risk_breaker_status
from forex_trader.domain.context import HealthState, ProviderHealth
from forex_trader.domain.models import jsonable
from forex_trader.domain.risk_advanced import EnhancedRiskPolicy


def _root_market_provider(market_data: object) -> object:
    return getattr(market_data, "provider", market_data)


def _capabilities(target: object, names: tuple[str, ...]) -> dict[str, bool]:
    return {name: callable(getattr(target, name, None)) for name in names}


def provider_snapshot(engine: object) -> dict[str, object]:
    """Return secret-free provider roles, capabilities and observed health.

    This is observability only. Capability presence never grants strategy or execution
    authority and a healthy transport does not mean a trade setup is eligible.
    """
    market_data = getattr(engine, "market_data")
    market_provider = _root_market_provider(market_data)
    broker = getattr(engine, "broker")
    health_reader = getattr(market_data, "health", None)
    health: ProviderHealth | None = None
    if callable(health_reader):
        value = health_reader()
        if isinstance(value, ProviderHealth):
            health = value

    market_name = type(market_provider).__name__
    broker_name = type(broker).__name__
    environment = "practice" if "OandaPractice" in broker_name or "OandaPractice" in market_name else "local_or_simulated"
    return {
        "schema": "provider-capability-snapshot-v1",
        "environment": environment,
        "market_data": {
            "wrapper": type(market_data).__name__,
            "provider": market_name,
            "capabilities": _capabilities(market_provider, ("quote", "candles", "candles_between", "instrument_spec")),
            "health": jsonable(health) if health is not None else None,
        },
        "broker": {
            "provider": broker_name,
            "capabilities": _capabilities(
                broker,
                (
                    "account",
                    "positions",
                    "place_order",
                    "transactions_since",
                    "transaction_stream",
                    "instrument_spec",
                ),
            ),
        },
        "interpretation": "provider health/capability is transport evidence only; it is not strategy eligibility or risk authorization",
    }


def breaker_snapshot(engine: object) -> dict[str, object]:
    risk_policy = getattr(engine, "risk_policy")
    if not isinstance(risk_policy, EnhancedRiskPolicy):
        return {
            "supported": False,
            "state": "not_applicable",
            "reason": "runtime risk policy is not EnhancedRiskPolicy",
        }
    try:
        account_id = str(getattr(engine, "broker").account().account_id)
    except (AttributeError, RuntimeError, ValueError) as exc:
        return {
            "supported": True,
            "state": "account_unavailable",
            "reason": f"{type(exc).__name__}: {exc}",
        }
    payload = risk_breaker_status(
        cast(RiskBreakerRepository, getattr(engine, "repository")),
        account_id=account_id,
        policy=risk_policy,
    )
    return {"supported": True, **jsonable(payload)}


def eligibility_layers(
    engine: object,
    instrument: str,
    *,
    observed_at: datetime | None = None,
) -> dict[str, object]:
    """Expose preflight layers without pretending they are a final trade decision."""
    normalized = instrument.strip().upper()
    if not normalized or "_" not in normalized:
        raise ValueError("instrument must be a normalized FX pair such as EUR_USD")
    instant = (observed_at or datetime.now(UTC)).astimezone(UTC)
    fusion = getattr(engine, "fusion_policy")
    fundamentals = getattr(engine, "fundamentals")
    assessment = fundamentals.assess_pair(normalized, as_of=instant)
    minimum_confidence = fusion.minimum_fundamental_confidence

    risk_policy = getattr(engine, "risk_policy")
    macro_guard = getattr(risk_policy, "macro_factor_guard", None)
    factor_map = getattr(macro_guard, "factor_map", {}) if macro_guard is not None else {}
    raw_factors = factor_map.get(normalized, ()) if isinstance(factor_map, Mapping) else ()
    factors = tuple(sorted(str(item) for item in raw_factors))
    classification_required = bool(getattr(macro_guard, "require_classification", False))
    classified = bool(factors) if classification_required else True

    repository = getattr(engine, "repository")
    event_reader = getattr(repository, "scheduled_events", None)
    event_support = callable(event_reader)
    relevant_events = []
    if event_support:
        base, quote = normalized.split("_", maxsplit=1)
        future = event_reader(start=instant, end=instant + timedelta(hours=24))
        relevant_events = [event for event in future if getattr(event, "currency", "") in {base, quote}]
    calendar_state = "populated" if relevant_events else "empty" if event_support else "unsupported"

    return {
        "schema": "execution-eligibility-layers-v1",
        "instrument": normalized,
        "observed_at": instant.isoformat(),
        "fundamental_preflight": {
            "required": bool(fusion.require_fundamentals),
            "confidence": str(assessment.confidence),
            "minimum_confidence": str(minimum_confidence),
            "eligible": (not fusion.require_fundamentals) or assessment.confidence >= minimum_confidence,
            "reasons": list(assessment.reasons),
        },
        "macro_factor": {
            "required": classification_required,
            "classified": classified,
            "factors": list(factors),
        },
        "calendar": {
            "repository_support": event_support,
            "state": calendar_state,
            "relevant_events_next_24h": len(relevant_events),
            "note": "an empty calendar is not evidence that no macro event exists",
        },
        "risk_breaker": breaker_snapshot(engine),
        "final_trade_eligible": None,
        "final_trade_eligible_reason": (
            "not asserted by preflight: technical setup, spread, quote freshness, context, portfolio risk and send-time execution gates remain authoritative"
        ),
    }


def basic_readiness_contract() -> dict[str, object]:
    return {
        "scope": "market_data_and_reconciliation",
        "requirements": {
            "calendar": False,
            "fundamentals": False,
            "institutional_flow": False,
            "reconciliation_when_orders_enabled": True,
        },
        "interpretation": "ready=true here is not equivalent to a trade candidate, risk grant or execution authorization",
    }
