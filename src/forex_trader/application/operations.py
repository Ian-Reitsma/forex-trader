from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Protocol

from forex_trader.domain.operations import (
    OperationalCategory,
    OperationalEvent,
    OperationalPolicy,
    OperationalSeverity,
    OperationalSnapshot,
)


class OperationalRepository(Protocol):
    def operational_events(
        self,
        *,
        limit: int = 1000,
        since: datetime | None = None,
        category: OperationalCategory | None = None,
        severity: OperationalSeverity | None = None,
    ) -> list[OperationalEvent]: ...

    def active_halts(self) -> list[dict[str, object]]: ...

    def all_execution_readiness(self) -> list[dict[str, object]]: ...


class OperationalTelemetryService:
    """Read-only operational projection over durable runtime evidence."""

    def __init__(
        self,
        repository: OperationalRepository,
        *,
        policy: OperationalPolicy | None = None,
        maximum_events: int = 10_000,
    ) -> None:
        if maximum_events < 100:
            raise ValueError("maximum_events must be at least 100")
        self.repository = repository
        self.policy = policy or OperationalPolicy()
        self.maximum_events = maximum_events

    def snapshot(
        self,
        *,
        hours: int = 24,
        now: datetime | None = None,
    ) -> OperationalSnapshot:
        if not 1 <= hours <= 24 * 30:
            raise ValueError("operational summary hours must be between 1 and 720")
        generated_at = (now or datetime.now(UTC)).astimezone(UTC)
        window = timedelta(hours=hours)
        events = self.repository.operational_events(
            limit=self.maximum_events,
            since=generated_at - window,
        )
        return self.policy.summarize(
            events,
            active_halts=self.repository.active_halts(),
            execution_readiness=self.repository.all_execution_readiness(),
            now=generated_at,
            window=window,
        )

    def events(
        self,
        *,
        limit: int = 200,
        hours: int = 24,
        category: OperationalCategory | None = None,
        severity: OperationalSeverity | None = None,
        now: datetime | None = None,
    ) -> list[OperationalEvent]:
        if not 1 <= limit <= 10_000:
            raise ValueError("operational event limit must be between 1 and 10000")
        if not 1 <= hours <= 24 * 30:
            raise ValueError("operational event hours must be between 1 and 720")
        generated_at = (now or datetime.now(UTC)).astimezone(UTC)
        return self.repository.operational_events(
            limit=limit,
            since=generated_at - timedelta(hours=hours),
            category=category,
            severity=severity,
        )
