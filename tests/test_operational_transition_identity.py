from __future__ import annotations

from datetime import UTC, datetime, timedelta

from forex_trader.domain.operations import OperationalCategory, OperationalSeverity
from forex_trader.infrastructure.advanced_repository import AdvancedTradingRepository


def test_rapid_readiness_transitions_are_distinct_and_current_state_is_authoritative(tmp_path) -> None:  # type: ignore[no-untyped-def]
    repository = AdvancedTradingRepository(tmp_path / "readiness.db")
    before = datetime.now(UTC) - timedelta(seconds=1)

    repository.set_execution_readiness("practice", False, broker_cursor="10", reason="initial sync incomplete")
    repository.set_execution_readiness("practice", True, broker_cursor="11", reason="reconciliation complete")

    events = repository.operational_events(
        since=before,
        category=OperationalCategory.READINESS,
    )
    assert len(events) == 2
    assert len({event.event_id for event in events}) == 2
    assert {event.event_key for event in events} == {
        "readiness:practice:not_ready",
        "readiness:practice:ready",
    }
    assert {event.severity for event in events} == {
        OperationalSeverity.CRITICAL,
        OperationalSeverity.INFO,
    }

    current = repository.execution_readiness("practice")
    assert current["ready"] is True
    assert current["broker_cursor"] == "11"
    assert current["reason"] == "reconciliation complete"
    updated_at = datetime.fromisoformat(str(current["updated_at"]))
    assert updated_at.tzinfo is not None


def test_repeated_halt_updates_preserve_each_transition_without_changing_current_state_semantics(tmp_path) -> None:  # type: ignore[no-untyped-def]
    repository = AdvancedTradingRepository(tmp_path / "halts.db")
    before = datetime.now(UTC) - timedelta(seconds=1)

    repository.set_halt("execution:practice", "unknown broker write")
    repository.set_halt("execution:practice", "protection verification failed")

    set_events = [
        event
        for event in repository.operational_events(
            since=before,
            category=OperationalCategory.HALT,
        )
        if event.event_key == "halt:execution:practice:set"
    ]
    assert len(set_events) == 2
    assert len({event.event_id for event in set_events}) == 2
    assert all(event.severity is OperationalSeverity.CRITICAL for event in set_events)
    assert {str(event.payload["reason"]) for event in set_events} == {
        "unknown broker write",
        "protection verification failed",
    }

    active = repository.active_halts()
    assert len(active) == 1
    assert active[0]["name"] == "execution:practice"
    assert active[0]["reason"] == "protection verification failed"

    repository.clear_halt("execution:practice")
    events = repository.operational_events(
        since=before,
        category=OperationalCategory.HALT,
    )
    assert len(events) == 3
    assert any(event.event_key == "halt:execution:practice:cleared" for event in events)
    assert repository.active_halts() == []
