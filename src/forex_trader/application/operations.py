from __future__ import annotations

from collections import Counter
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

    def prometheus(self, *, hours: int = 24, now: datetime | None = None) -> str:
        snapshot = self.snapshot(hours=hours, now=now)
        lines = [
            "# HELP forex_operational_window_seconds Operational summary lookback window in seconds.",
            "# TYPE forex_operational_window_seconds gauge",
            f"forex_operational_window_seconds {(snapshot.generated_at - snapshot.window_start).total_seconds():.0f}",
            "# HELP forex_operational_events_total Durable operational events observed in the summary window.",
            "# TYPE forex_operational_events_total gauge",
        ]
        for category, count in snapshot.event_counts.items():
            lines.append(f'forex_operational_events_total{{category="{_label(category)}"}} {count}')
        lines.extend(
            (
                "# HELP forex_operational_severity_total Operational events by severity in the summary window.",
                "# TYPE forex_operational_severity_total gauge",
            )
        )
        for severity, count in snapshot.severity_counts.items():
            lines.append(f'forex_operational_severity_total{{severity="{_label(severity)}"}} {count}')
        lines.extend(
            (
                "# HELP forex_decisions_total Decisions by disposition in the summary window.",
                "# TYPE forex_decisions_total gauge",
            )
        )
        for disposition, count in snapshot.decision_dispositions.items():
            lines.append(f'forex_decisions_total{{disposition="{_label(disposition)}"}} {count}')
        lines.extend(
            (
                "# HELP forex_risk_authorizations_total Risk authorizations by disposition in the summary window.",
                "# TYPE forex_risk_authorizations_total gauge",
            )
        )
        for disposition, count in snapshot.risk_dispositions.items():
            lines.append(f'forex_risk_authorizations_total{{disposition="{_label(disposition)}"}} {count}')
        lines.extend(
            (
                "# HELP forex_execution_status_total Broker execution outcomes by status in the summary window.",
                "# TYPE forex_execution_status_total gauge",
            )
        )
        for execution_status, count in snapshot.execution_statuses.items():
            lines.append(f'forex_execution_status_total{{status="{_label(execution_status)}"}} {count}')
        lines.extend(
            (
                "# HELP forex_provider_state Latest observed provider health state; one series is 1 for each provider/state pair.",
                "# TYPE forex_provider_state gauge",
            )
        )
        for provider, state in snapshot.provider_states.items():
            lines.append(
                f'forex_provider_state{{provider="{_label(provider)}",state="{_label(state)}"}} 1'
            )
        lines.extend(
            (
                "# HELP forex_active_halts Number of persistent active trading halts.",
                "# TYPE forex_active_halts gauge",
                f"forex_active_halts {len(snapshot.active_halts)}",
                "# HELP forex_execution_not_ready_accounts Number of broker accounts not reconciliation-ready.",
                "# TYPE forex_execution_not_ready_accounts gauge",
                f"forex_execution_not_ready_accounts {sum(not bool(row.get('ready')) for row in snapshot.execution_readiness)}",
                "# HELP forex_operational_alerts Number of current operational alerts by severity.",
                "# TYPE forex_operational_alerts gauge",
            )
        )
        alert_counts = Counter(alert.severity.value for alert in snapshot.alerts)
        for severity in OperationalSeverity:
            lines.append(
                f'forex_operational_alerts{{severity="{severity.value}"}} {alert_counts.get(severity.value, 0)}'
            )
        return "\n".join(lines) + "\n"


def _label(value: str) -> str:
    return value.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n")
