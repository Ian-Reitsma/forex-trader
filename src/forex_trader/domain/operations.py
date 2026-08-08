from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from typing import Iterable, Mapping


class OperationalSeverity(StrEnum):
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"
    CRITICAL = "critical"


class OperationalCategory(StrEnum):
    DECISION = "decision"
    PROVIDER = "provider"
    RISK = "risk"
    EXECUTION = "execution"
    HALT = "halt"
    READINESS = "readiness"
    SYSTEM = "system"


@dataclass(frozen=True, slots=True)
class OperationalEvent:
    event_id: str
    category: OperationalCategory
    severity: OperationalSeverity
    event_key: str
    observed_at: datetime
    payload: dict[str, object]

    def __post_init__(self) -> None:
        if not self.event_id.strip():
            raise ValueError("operational event_id is required")
        if not self.event_key.strip():
            raise ValueError("operational event_key is required")
        if self.observed_at.tzinfo is None:
            raise ValueError("operational event observed_at must be timezone-aware")


@dataclass(frozen=True, slots=True)
class OperationalAlert:
    code: str
    severity: OperationalSeverity
    message: str
    count: int = 1
    source: str | None = None

    def __post_init__(self) -> None:
        if not self.code.strip() or not self.message.strip():
            raise ValueError("operational alert code and message are required")
        if self.count < 1:
            raise ValueError("operational alert count must be positive")


@dataclass(frozen=True, slots=True)
class OperationalSnapshot:
    generated_at: datetime
    window_start: datetime
    events_considered: int
    event_counts: dict[str, int]
    severity_counts: dict[str, int]
    decision_dispositions: dict[str, int]
    rejection_codes: dict[str, int]
    strategy_policies: dict[str, int]
    regimes: dict[str, int]
    risk_dispositions: dict[str, int]
    risk_veto_reasons: dict[str, int]
    execution_statuses: dict[str, int]
    provider_states: dict[str, str]
    active_halts: tuple[dict[str, object], ...]
    execution_readiness: tuple[dict[str, object], ...]
    alerts: tuple[OperationalAlert, ...]

    def __post_init__(self) -> None:
        if self.generated_at.tzinfo is None or self.window_start.tzinfo is None:
            raise ValueError("operational snapshot times must be timezone-aware")
        if self.window_start > self.generated_at:
            raise ValueError("operational snapshot window_start cannot be in the future")
        if self.events_considered < 0:
            raise ValueError("events_considered cannot be negative")


@dataclass(frozen=True, slots=True)
class OperationalPolicy:
    provider_unavailable_is_critical: bool = True
    provider_degraded_is_warning: bool = True
    provider_rate_limited_is_warning: bool = True
    provider_runtime_error_is_error: bool = True
    execution_unknown_is_critical: bool = True
    reconciliation_not_ready_is_critical: bool = True
    active_halt_is_critical: bool = True
    evaluation_error_is_error: bool = True

    def summarize(
        self,
        events: Iterable[OperationalEvent],
        *,
        active_halts: Iterable[Mapping[str, object]] = (),
        execution_readiness: Iterable[Mapping[str, object]] = (),
        now: datetime | None = None,
        window: timedelta = timedelta(hours=24),
    ) -> OperationalSnapshot:
        generated_at = (now or datetime.now(UTC)).astimezone(UTC)
        if window <= timedelta(0):
            raise ValueError("operational telemetry window must be positive")
        window_start = generated_at - window
        recent = tuple(
            event
            for event in events
            if window_start <= event.observed_at.astimezone(UTC) <= generated_at
        )
        halt_rows = tuple(dict(item) for item in active_halts)
        readiness_rows = tuple(dict(item) for item in execution_readiness)

        event_counts = Counter(event.category.value for event in recent)
        severity_counts = Counter(event.severity.value for event in recent)
        decisions: Counter[str] = Counter()
        rejection_codes: Counter[str] = Counter()
        strategies: Counter[str] = Counter()
        regimes: Counter[str] = Counter()
        risk_dispositions: Counter[str] = Counter()
        risk_reasons: Counter[str] = Counter()
        execution_statuses: Counter[str] = Counter()
        provider_states: dict[
            str,
            tuple[datetime, str, bool, OperationalSeverity],
        ] = {}
        evaluation_errors = 0

        for event in recent:
            payload = event.payload
            if event.category is OperationalCategory.DECISION:
                disposition = _text(payload.get("disposition"))
                if disposition:
                    decisions[disposition] += 1
                rejection_code = _text(payload.get("rejection_code"))
                if rejection_code:
                    rejection_codes[rejection_code] += 1
                selected_policy = _text(payload.get("selected_policy"))
                if selected_policy:
                    strategies[selected_policy] += 1
                regime = _text(payload.get("regime"))
                if regime:
                    regimes[regime] += 1
                if payload.get("evaluation_error"):
                    evaluation_errors += 1
            elif event.category is OperationalCategory.RISK:
                disposition = _text(payload.get("disposition"))
                if disposition:
                    risk_dispositions[disposition] += 1
                if disposition == "denied":
                    for reason in _string_sequence(payload.get("reasons")):
                        risk_reasons[_normalize_reason(reason)] += 1
            elif event.category is OperationalCategory.EXECUTION:
                status = _text(payload.get("status"))
                if status:
                    execution_statuses[status] += 1
            elif event.category is OperationalCategory.PROVIDER:
                provider = _text(payload.get("provider"))
                state = _text(payload.get("state"))
                if provider and state:
                    previous = provider_states.get(provider)
                    if previous is None or event.observed_at > previous[0]:
                        provider_states[provider] = (
                            event.observed_at,
                            state,
                            bool(payload.get("rate_limited")),
                            event.severity,
                        )

        alerts: list[OperationalAlert] = []
        if halt_rows and self.active_halt_is_critical:
            alerts.append(
                OperationalAlert(
                    "ACTIVE_SYSTEM_HALT",
                    OperationalSeverity.CRITICAL,
                    "one or more persistent system halts are active",
                    len(halt_rows),
                )
            )
        not_ready = tuple(row for row in readiness_rows if not bool(row.get("ready")))
        if not_ready and self.reconciliation_not_ready_is_critical:
            alerts.append(
                OperationalAlert(
                    "EXECUTION_NOT_READY",
                    OperationalSeverity.CRITICAL,
                    "one or more broker accounts are not reconciliation-ready",
                    len(not_ready),
                )
            )
        unresolved_execution = sum(
            execution_statuses.get(status, 0)
            for status in ("unknown", "reconciliation_required", "emergency_close")
        )
        if unresolved_execution and self.execution_unknown_is_critical:
            alerts.append(
                OperationalAlert(
                    "EXECUTION_UNCERTAINTY",
                    OperationalSeverity.CRITICAL,
                    "recent executions contain unresolved or emergency broker states",
                    unresolved_execution,
                )
            )
        for provider, (_, state, rate_limited, provider_severity) in sorted(provider_states.items()):
            if state == "unavailable" and self.provider_unavailable_is_critical:
                alerts.append(
                    OperationalAlert(
                        "PROVIDER_UNAVAILABLE",
                        OperationalSeverity.CRITICAL,
                        f"provider {provider} is unavailable",
                        source=provider,
                    )
                )
            elif state == "error" and self.provider_runtime_error_is_error:
                alerts.append(
                    OperationalAlert(
                        "PROVIDER_RUNTIME_ERROR",
                        OperationalSeverity.ERROR,
                        f"provider {provider} recorded a runtime error",
                        source=provider,
                    )
                )
            elif state == "degraded" and self.provider_degraded_is_warning:
                alerts.append(
                    OperationalAlert(
                        "PROVIDER_DEGRADED",
                        OperationalSeverity.WARNING,
                        f"provider {provider} is degraded",
                        source=provider,
                    )
                )
            if rate_limited and self.provider_rate_limited_is_warning:
                alerts.append(
                    OperationalAlert(
                        "PROVIDER_RATE_LIMITED",
                        OperationalSeverity.WARNING,
                        f"provider {provider} is rate limited",
                        source=provider,
                    )
                )
            if (
                provider_severity is OperationalSeverity.ERROR
                and state not in {"error", "unavailable"}
                and self.provider_runtime_error_is_error
            ):
                alerts.append(
                    OperationalAlert(
                        "PROVIDER_RUNTIME_ERROR",
                        OperationalSeverity.ERROR,
                        f"provider {provider} emitted an error-severity operational event",
                        source=provider,
                    )
                )
        if evaluation_errors and self.evaluation_error_is_error:
            alerts.append(
                OperationalAlert(
                    "EVALUATION_ERRORS",
                    OperationalSeverity.ERROR,
                    "recent decision evaluations recorded runtime errors",
                    evaluation_errors,
                )
            )

        severity_rank = {
            OperationalSeverity.CRITICAL: 0,
            OperationalSeverity.ERROR: 1,
            OperationalSeverity.WARNING: 2,
            OperationalSeverity.INFO: 3,
        }
        alerts.sort(key=lambda item: (severity_rank[item.severity], item.code, item.source or ""))
        return OperationalSnapshot(
            generated_at=generated_at,
            window_start=window_start,
            events_considered=len(recent),
            event_counts=dict(sorted(event_counts.items())),
            severity_counts=dict(sorted(severity_counts.items())),
            decision_dispositions=dict(sorted(decisions.items())),
            rejection_codes=_top_counter(rejection_codes),
            strategy_policies=_top_counter(strategies),
            regimes=_top_counter(regimes),
            risk_dispositions=dict(sorted(risk_dispositions.items())),
            risk_veto_reasons=_top_counter(risk_reasons),
            execution_statuses=dict(sorted(execution_statuses.items())),
            provider_states={key: value[1] for key, value in sorted(provider_states.items())},
            active_halts=halt_rows,
            execution_readiness=readiness_rows,
            alerts=tuple(alerts),
        )


def _text(value: object) -> str:
    return "" if value is None else str(value).strip()


def _string_sequence(value: object) -> tuple[str, ...]:
    if not isinstance(value, (list, tuple)):
        return ()
    return tuple(str(item) for item in value if str(item).strip())


def _normalize_reason(reason: str) -> str:
    """Aggregate dynamic reasons without collapsing materially different veto families."""

    text = reason.strip()
    for marker in (":", "="):
        if marker in text:
            prefix = text.split(marker, 1)[0].strip()
            if prefix:
                return prefix
    return text[:160]


def _top_counter(counter: Counter[str], limit: int = 20) -> dict[str, int]:
    ordered = sorted(counter.items(), key=lambda item: (-item[1], item[0]))[:limit]
    return dict(ordered)
