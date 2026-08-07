from __future__ import annotations

from datetime import timedelta
from decimal import Decimal

from forex_trader.domain.context import (
    DataQualitySnapshot,
    HealthState,
    ProviderHealth,
    ReadinessPolicy,
    TradingReadiness,
)


def assess_engine_readiness(
    engine: object,
    instrument: str,
    *,
    policy: ReadinessPolicy | None = None,
) -> tuple[DataQualitySnapshot, tuple[ProviderHealth, ...], TradingReadiness]:
    market_data = getattr(engine, "market_data")
    lower = list(market_data.candles(instrument, "M5", 200))
    quote = market_data.quote(instrument)
    completed = [item for item in lower if item.complete]
    if len(completed) < 2:
        snapshot = DataQualitySnapshot(
            quote.time,
            missing_bars=1,
            reconciliation_ready=_reconciliation_ready(engine),
        )
        readiness = (policy or ReadinessPolicy()).evaluate(
            snapshot,
            _provider_health(engine, quote.time),
            require_calendar=False,
            require_fundamentals=False,
            require_flow=False,
            require_reconciliation=bool(getattr(engine, "enable_paper_orders", False)),
        )
        return snapshot, _provider_health(engine, quote.time), readiness

    timestamp_reversal = any(current.time <= previous.time for previous, current in zip(completed, completed[1:]))
    steps = [current.time - previous.time for previous, current in zip(completed, completed[1:]) if current.time > previous.time]
    normal_steps = [step for step in steps if step <= timedelta(hours=6)]
    step = min(normal_steps) if normal_steps else steps[-1]
    missing_bars = sum(
        max(0, int(gap.total_seconds() // step.total_seconds()) - 1)
        for gap in normal_steps
        if step.total_seconds() > 0 and gap > step * 1.5
    )
    last_close = completed[-1].time + step
    candle_age = max(Decimal("0"), Decimal(str((quote.time - last_close).total_seconds())))
    snapshot = DataQualitySnapshot(
        observed_at=quote.time,
        quote_age_seconds=Decimal("0"),
        candle_watermark_age_seconds=candle_age,
        missing_bars=missing_bars,
        timestamp_reversal=timestamp_reversal,
        reconciliation_ready=_reconciliation_ready(engine),
    )
    providers = _provider_health(engine, quote.time)
    readiness = (policy or ReadinessPolicy()).evaluate(
        snapshot,
        providers,
        require_calendar=False,
        require_fundamentals=False,
        require_flow=False,
        require_reconciliation=bool(getattr(engine, "enable_paper_orders", False)),
    )
    return snapshot, providers, readiness


def _reconciliation_ready(engine: object) -> bool:
    if not bool(getattr(engine, "enable_paper_orders", False)):
        return True
    repository = getattr(engine, "repository")
    checker = getattr(repository, "execution_ready", None)
    broker = getattr(engine, "broker")
    try:
        account_id = broker.account().account_id
    except (AttributeError, RuntimeError, ValueError):
        return False
    return bool(checker(account_id)) if checker is not None else False


def _provider_health(engine: object, observed_at) -> tuple[ProviderHealth, ...]:  # type: ignore[no-untyped-def]
    provider = getattr(engine, "market_data")
    health = getattr(provider, "health", None)
    if callable(health):
        result = health()
        if isinstance(result, ProviderHealth):
            return (result,)
    return (
        ProviderHealth(
            provider=type(provider).__name__,
            state=HealthState.DEGRADED,
            observed_at=observed_at,
            detail="adapter does not expose an explicit provider-health contract",
        ),
    )
