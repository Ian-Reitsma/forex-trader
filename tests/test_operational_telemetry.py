from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import uuid4

import pytest

from forex_trader.application.operations import OperationalTelemetryService
from forex_trader.domain.enums import DecisionDisposition, Direction, OrderStatus, RiskDisposition
from forex_trader.domain.models import DecisionTrace, OrderResult, Quote, RiskAuthorization, TradeCandidate
from forex_trader.domain.operations import (
    OperationalAlert,
    OperationalCategory,
    OperationalEvent,
    OperationalPolicy,
    OperationalSeverity,
    OperationalSnapshot,
)
from forex_trader.infrastructure.advanced_repository import AdvancedTradingRepository

NOW = datetime(2026, 8, 8, 14, 0, tzinfo=UTC)


def _event(
    event_id: str,
    category: OperationalCategory,
    severity: OperationalSeverity,
    payload: dict[str, object],
    *,
    seconds: int = 0,
) -> OperationalEvent:
    return OperationalEvent(
        event_id,
        category,
        severity,
        event_id,
        NOW + timedelta(seconds=seconds),
        payload,
    )


def _candidate() -> TradeCandidate:
    return TradeCandidate(
        candidate_id=uuid4(),
        instrument="EUR_USD",
        direction=Direction.LONG,
        disposition=DecisionDisposition.TRADE,
        score=Decimal("0.9"),
        entry_price=Decimal("1.1000"),
        stop_loss=Decimal("1.0990"),
        take_profit=Decimal("1.1030"),
        technical_score=Decimal("0.9"),
        fundamental_score=Decimal("0.7"),
        reasons=(),
        signal_time=NOW,
        execution_key="telemetry-test",
        rejection_code=None,
        evidence={
            "selected_policy": "sweep_reclaim:v1",
            "regime": "trend",
            "independent_confirmation_count": 3,
            "independent_source_count": 3,
            "external_context": {
                "provider_health": (
                    {
                        "provider": "calendar",
                        "state": "healthy",
                        "observed_at": NOW.isoformat(),
                        "heartbeat_age_seconds": "1",
                        "rate_limited": True,
                        "detail": "quota pressure",
                    },
                    {
                        "provider": "flow",
                        "state": "unavailable",
                        "observed_at": NOW.isoformat(),
                        "heartbeat_age_seconds": "90",
                        "rate_limited": False,
                        "detail": "stale",
                    },
                ),
                "errors": ("cross_asset:RuntimeError:vendor timeout",),
            },
        },
    )


def _trace(*, execution_status: OrderStatus = OrderStatus.UNKNOWN) -> DecisionTrace:
    candidate = _candidate()
    risk = RiskAuthorization(
        authorization_id=uuid4(),
        candidate_id=candidate.candidate_id,
        disposition=RiskDisposition.DENIED,
        units=0,
        risk_amount=Decimal("0"),
        reasons=("macro factor exposure limit exceeded: usd_rates 3.1>2.5",),
        account_id="practice",
        risk_policy_version="practice-risk-v0.7.24",
        limits_consumed={"macro_factor_exposure_fraction": "2.5"},
    )
    order = OrderResult(
        client_order_id="telemetry-order",
        provider_order_id=None,
        status=execution_status,
        instrument="EUR_USD",
        units=100,
        fill_price=None,
        created_at=NOW,
    )
    return DecisionTrace(
        trace_id=uuid4(),
        instrument="EUR_USD",
        candidate=candidate,
        risk=risk,
        order=order,
        quote=Quote("EUR_USD", Decimal("1.0999"), Decimal("1.1001"), NOW),
        created_at=NOW,
        metadata={},
    )


def test_operational_contract_validation() -> None:
    with pytest.raises(ValueError, match="event_id"):
        OperationalEvent("", OperationalCategory.SYSTEM, OperationalSeverity.INFO, "x", NOW, {})
    with pytest.raises(ValueError, match="event_key"):
        OperationalEvent("x", OperationalCategory.SYSTEM, OperationalSeverity.INFO, "", NOW, {})
    with pytest.raises(ValueError, match="timezone-aware"):
        OperationalEvent("x", OperationalCategory.SYSTEM, OperationalSeverity.INFO, "x", NOW.replace(tzinfo=None), {})
    with pytest.raises(ValueError, match="code and message"):
        OperationalAlert("", OperationalSeverity.INFO, "x")
    with pytest.raises(ValueError, match="positive"):
        OperationalAlert("X", OperationalSeverity.INFO, "x", count=0)
    with pytest.raises(ValueError, match="timezone-aware"):
        OperationalSnapshot(
            NOW.replace(tzinfo=None), NOW, 0, {}, {}, {}, {}, {}, {}, {}, {}, {}, {}, (), (), ()
        )
    with pytest.raises(ValueError, match="future"):
        OperationalSnapshot(
            NOW, NOW + timedelta(seconds=1), 0, {}, {}, {}, {}, {}, {}, {}, {}, {}, {}, (), (), ()
        )
    with pytest.raises(ValueError, match="negative"):
        OperationalSnapshot(NOW, NOW, -1, {}, {}, {}, {}, {}, {}, {}, {}, {}, {}, (), (), ())


def test_policy_summarizes_runtime_failures_and_provider_states() -> None:
    events = [
        _event(
            "decision",
            OperationalCategory.DECISION,
            OperationalSeverity.ERROR,
            {
                "disposition": "abstain",
                "rejection_code": "INDEPENDENT_CONFIRMATION_MISSING",
                "selected_policy": "sweep_reclaim:v1",
                "regime": "trend",
                "evaluation_error": "provider error",
            },
        ),
        _event(
            "risk",
            OperationalCategory.RISK,
            OperationalSeverity.WARNING,
            {
                "disposition": "denied",
                "reasons": (
                    "macro factor exposure limit exceeded: usd_rates 3.1>2.5",
                    "reserved/pending portfolio risk limit reached",
                ),
            },
        ),
        _event(
            "execution",
            OperationalCategory.EXECUTION,
            OperationalSeverity.CRITICAL,
            {"status": "unknown"},
        ),
        _event(
            "calendar",
            OperationalCategory.PROVIDER,
            OperationalSeverity.WARNING,
            {"provider": "calendar", "state": "healthy", "rate_limited": True},
        ),
        _event(
            "flow",
            OperationalCategory.PROVIDER,
            OperationalSeverity.CRITICAL,
            {"provider": "flow", "state": "unavailable", "rate_limited": False},
        ),
        _event(
            "news",
            OperationalCategory.PROVIDER,
            OperationalSeverity.WARNING,
            {"provider": "news", "state": "degraded", "rate_limited": False},
        ),
        _event(
            "external",
            OperationalCategory.PROVIDER,
            OperationalSeverity.ERROR,
            {"provider": "external_context", "state": "error"},
        ),
    ]
    snapshot = OperationalPolicy().summarize(
        events,
        active_halts=({"name": "execution:practice", "reason": "uncertain"},),
        execution_readiness=({"account_id": "practice", "ready": False},),
        now=NOW + timedelta(minutes=1),
    )
    assert snapshot.events_considered == len(events)
    assert snapshot.decision_dispositions == {"abstain": 1}
    assert snapshot.rejection_codes == {"INDEPENDENT_CONFIRMATION_MISSING": 1}
    assert snapshot.strategy_policies == {"sweep_reclaim:v1": 1}
    assert snapshot.regimes == {"trend": 1}
    assert snapshot.risk_dispositions == {"denied": 1}
    assert snapshot.risk_veto_reasons["macro factor exposure limit exceeded"] == 1
    assert snapshot.execution_statuses == {"unknown": 1}
    assert snapshot.provider_states == {
        "calendar": "healthy",
        "external_context": "error",
        "flow": "unavailable",
        "news": "degraded",
    }
    alert_codes = {alert.code for alert in snapshot.alerts}
    assert {
        "ACTIVE_SYSTEM_HALT",
        "EXECUTION_NOT_READY",
        "EXECUTION_UNCERTAINTY",
        "PROVIDER_RATE_LIMITED",
        "PROVIDER_UNAVAILABLE",
        "PROVIDER_DEGRADED",
        "PROVIDER_RUNTIME_ERROR",
        "EVALUATION_ERRORS",
    } <= alert_codes


def test_policy_uses_latest_provider_health_and_window_boundary() -> None:
    events = [
        _event(
            "old-flow",
            OperationalCategory.PROVIDER,
            OperationalSeverity.CRITICAL,
            {"provider": "flow", "state": "unavailable"},
            seconds=-3600,
        ),
        _event(
            "new-flow",
            OperationalCategory.PROVIDER,
            OperationalSeverity.INFO,
            {"provider": "flow", "state": "healthy"},
            seconds=1,
        ),
        _event(
            "future",
            OperationalCategory.EXECUTION,
            OperationalSeverity.CRITICAL,
            {"status": "unknown"},
            seconds=3600,
        ),
    ]
    snapshot = OperationalPolicy().summarize(
        events,
        now=NOW + timedelta(seconds=10),
        window=timedelta(minutes=30),
    )
    assert snapshot.provider_states == {"flow": "healthy"}
    assert "PROVIDER_UNAVAILABLE" not in {alert.code for alert in snapshot.alerts}
    assert "EXECUTION_UNCERTAINTY" not in {alert.code for alert in snapshot.alerts}
    with pytest.raises(ValueError, match="positive"):
        OperationalPolicy().summarize([], now=NOW, window=timedelta(0))


def test_repository_derives_idempotent_events_from_decision_trace(tmp_path) -> None:  # type: ignore[no-untyped-def]
    repository = AdvancedTradingRepository(tmp_path / "ops.db")
    trace = _trace()
    repository.save_trace(trace)
    repository.save_trace(trace)

    events = repository.operational_events(since=NOW - timedelta(minutes=1))
    keys = {event.event_key for event in events}
    assert "decision:EUR_USD:trade" in keys
    assert "risk:EUR_USD:denied" in keys
    assert "execution:EUR_USD:unknown" in keys
    assert "provider:calendar:healthy" in keys
    assert "provider:flow:unavailable" in keys
    assert "provider:runtime_error" in keys
    assert len(events) == 6

    critical = repository.operational_events(
        since=NOW - timedelta(minutes=1),
        severity=OperationalSeverity.CRITICAL,
    )
    assert {event.event_key for event in critical} == {
        "execution:EUR_USD:unknown",
        "provider:flow:unavailable",
    }
    provider_events = repository.operational_events(
        since=NOW - timedelta(minutes=1),
        category=OperationalCategory.PROVIDER,
    )
    assert len(provider_events) == 3
    with pytest.raises(ValueError, match="timezone-aware"):
        repository.operational_events(since=NOW.replace(tzinfo=None))


def test_repository_records_halt_and_readiness_state(tmp_path) -> None:  # type: ignore[no-untyped-def]
    repository = AdvancedTradingRepository(tmp_path / "state.db")
    repository.set_execution_readiness("practice", False, reason="initial reconciliation required")
    assert repository.all_execution_readiness()[0]["ready"] is False
    repository.set_halt("execution:practice", "unknown broker write")
    assert repository.active_halts()[0]["name"] == "execution:practice"

    events = repository.operational_events()
    assert any(event.category is OperationalCategory.READINESS for event in events)
    assert any(event.category is OperationalCategory.HALT and event.severity is OperationalSeverity.CRITICAL for event in events)

    repository.clear_halt("execution:practice")
    assert repository.active_halts() == []
    assert any(event.event_key == "halt:execution:practice:cleared" for event in repository.operational_events())
    repository.clear_halt("missing")


def test_operational_service_validates_queries_and_emits_prometheus(tmp_path) -> None:  # type: ignore[no-untyped-def]
    repository = AdvancedTradingRepository(tmp_path / "service.db")
    trace = _trace(execution_status=OrderStatus.PROTECTED)
    repository.save_trace(trace)
    repository.set_execution_readiness("practice", True, reason="synced")
    service = OperationalTelemetryService(repository)

    snapshot = service.snapshot(hours=24, now=NOW + timedelta(minutes=1))
    assert snapshot.execution_statuses == {"protected": 1}
    filtered = service.events(
        limit=20,
        hours=24,
        category=OperationalCategory.EXECUTION,
        now=NOW + timedelta(minutes=1),
    )
    assert len(filtered) == 1
    metrics = service.prometheus(hours=24, now=NOW + timedelta(minutes=1))
    assert 'forex_operational_events_total{category="execution"} 1' in metrics
    assert 'forex_execution_status_total{status="protected"} 1' in metrics
    assert "forex_active_halts 0" in metrics
    assert "forex_execution_not_ready_accounts 0" in metrics

    with pytest.raises(ValueError, match="at least 100"):
        OperationalTelemetryService(repository, maximum_events=99)
    with pytest.raises(ValueError, match="between 1 and 720"):
        service.snapshot(hours=0)
    with pytest.raises(ValueError, match="between 1 and 10000"):
        service.events(limit=0)
    with pytest.raises(ValueError, match="between 1 and 720"):
        service.events(hours=721)
