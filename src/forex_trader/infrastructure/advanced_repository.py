from __future__ import annotations

import json
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

from forex_trader.domain.models import DecisionTrace, jsonable
from forex_trader.domain.operations import OperationalCategory, OperationalEvent, OperationalSeverity
from forex_trader.domain.setup_lifecycle import SetupInstance, SetupLifecycleState, SetupTransition
from forex_trader.infrastructure.trading_repository import TradingRepository


class AdvancedTradingRepository(TradingRepository):
    """Durable Phase A-D state and operational evidence for the runtime control path."""

    def __init__(self, path: str | Path = ":memory:") -> None:
        super().__init__(path)
        self._migrate_advanced_state()

    def _migrate_advanced_state(self) -> None:
        with self._connection:
            self._connection.execute(
                """
                CREATE TABLE IF NOT EXISTS execution_readiness (
                    account_id TEXT PRIMARY KEY,
                    ready INTEGER NOT NULL,
                    broker_cursor TEXT,
                    reason TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
                """
            )
            self._connection.execute(
                """
                CREATE TABLE IF NOT EXISTS setup_instances (
                    setup_id TEXT PRIMARY KEY,
                    instrument TEXT NOT NULL,
                    setup_family TEXT NOT NULL,
                    policy_version TEXT NOT NULL,
                    state TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    anchor_id TEXT NOT NULL,
                    payload_json TEXT NOT NULL
                )
                """
            )
            self._connection.execute(
                """
                CREATE TABLE IF NOT EXISTS setup_transitions (
                    transition_id TEXT PRIMARY KEY,
                    setup_id TEXT NOT NULL,
                    available_at TEXT NOT NULL,
                    payload_json TEXT NOT NULL
                )
                """
            )
            self._connection.execute(
                "CREATE INDEX IF NOT EXISTS idx_setup_transitions ON setup_transitions(setup_id, available_at, transition_id)"
            )
            self._connection.execute(
                """
                CREATE TABLE IF NOT EXISTS advanced_risk_state (
                    account_id TEXT PRIMARY KEY,
                    peak_nav TEXT NOT NULL,
                    loss_streak INTEGER NOT NULL,
                    reserved_risk TEXT NOT NULL,
                    pending_risk TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
                """
            )
            self._connection.execute(
                """
                CREATE TABLE IF NOT EXISTS operational_events (
                    event_id TEXT PRIMARY KEY,
                    category TEXT NOT NULL,
                    severity TEXT NOT NULL,
                    event_key TEXT NOT NULL,
                    observed_at TEXT NOT NULL,
                    payload_json TEXT NOT NULL
                )
                """
            )
            self._connection.execute(
                "CREATE INDEX IF NOT EXISTS idx_operational_events_time ON operational_events(observed_at DESC, event_id)"
            )
            self._connection.execute(
                "CREATE INDEX IF NOT EXISTS idx_operational_events_category ON operational_events(category, observed_at DESC)"
            )

    def save_trace(self, trace: DecisionTrace) -> None:
        """Persist a decision trace and derive idempotent operational events from it."""

        super().save_trace(trace)
        evidence = trace.candidate.evidence
        decision_payload: dict[str, object] = {
            "trace_id": str(trace.trace_id),
            "instrument": trace.instrument,
            "disposition": trace.candidate.disposition.value,
            "rejection_code": trace.candidate.rejection_code,
            "score": str(trace.candidate.score),
            "selected_policy": evidence.get("selected_policy"),
            "regime": evidence.get("regime"),
            "independent_confirmation_count": evidence.get("independent_confirmation_count"),
            "independent_source_count": evidence.get("independent_source_count"),
            "evaluation_error": trace.metadata.get("evaluation_error") or trace.metadata.get("error"),
        }
        self._upsert_operational_event(
            OperationalEvent(
                event_id=f"trace:{trace.trace_id}:decision",
                category=OperationalCategory.DECISION,
                severity=(
                    OperationalSeverity.ERROR
                    if decision_payload["evaluation_error"]
                    else OperationalSeverity.INFO
                ),
                event_key=f"decision:{trace.instrument}:{trace.candidate.disposition.value}",
                observed_at=trace.created_at,
                payload=decision_payload,
            )
        )

        if trace.risk is not None:
            self._upsert_operational_event(
                OperationalEvent(
                    event_id=f"trace:{trace.trace_id}:risk",
                    category=OperationalCategory.RISK,
                    severity=(
                        OperationalSeverity.WARNING
                        if trace.risk.disposition.value == "denied"
                        else OperationalSeverity.INFO
                    ),
                    event_key=f"risk:{trace.instrument}:{trace.risk.disposition.value}",
                    observed_at=trace.created_at,
                    payload={
                        "trace_id": str(trace.trace_id),
                        "instrument": trace.instrument,
                        "disposition": trace.risk.disposition.value,
                        "units": trace.risk.units,
                        "risk_amount": str(trace.risk.risk_amount),
                        "maximum_loss": None
                        if trace.risk.maximum_loss is None
                        else str(trace.risk.maximum_loss),
                        "risk_policy_version": trace.risk.risk_policy_version,
                        "reasons": trace.risk.reasons,
                        "limits_consumed": trace.risk.limits_consumed,
                    },
                )
            )

        if trace.order is not None:
            status = trace.order.status.value
            critical = status in {"unknown", "reconciliation_required", "emergency_close"}
            warning = status in {"rejected", "cancelled"}
            severity = (
                OperationalSeverity.CRITICAL
                if critical
                else OperationalSeverity.WARNING
                if warning
                else OperationalSeverity.INFO
            )
            self._upsert_operational_event(
                OperationalEvent(
                    event_id=f"trace:{trace.trace_id}:execution",
                    category=OperationalCategory.EXECUTION,
                    severity=severity,
                    event_key=f"execution:{trace.instrument}:{status}",
                    observed_at=trace.order.broker_time or trace.order.created_at,
                    payload={
                        "trace_id": str(trace.trace_id),
                        "instrument": trace.instrument,
                        "status": status,
                        "units": trace.order.units,
                        "protection_confirmed": trace.order.protection_confirmed,
                        "provider_order_id": trace.order.provider_order_id,
                        "provider_trade_id": trace.order.provider_trade_id,
                    },
                )
            )

        external = evidence.get("external_context")
        if isinstance(external, dict):
            raw_health = external.get("provider_health")
            if isinstance(raw_health, (list, tuple)):
                for raw in raw_health:
                    if not isinstance(raw, dict):
                        continue
                    provider = str(raw.get("provider") or "").strip()
                    state = str(raw.get("state") or "").strip()
                    if not provider or not state:
                        continue
                    severity = (
                        OperationalSeverity.CRITICAL
                        if state == "unavailable"
                        else OperationalSeverity.WARNING
                        if state == "degraded" or bool(raw.get("rate_limited"))
                        else OperationalSeverity.INFO
                    )
                    observed = _parse_aware(str(raw.get("observed_at") or ""), fallback=trace.created_at)
                    self._upsert_operational_event(
                        OperationalEvent(
                            event_id=f"trace:{trace.trace_id}:provider:{provider}",
                            category=OperationalCategory.PROVIDER,
                            severity=severity,
                            event_key=f"provider:{provider}:{state}",
                            observed_at=observed,
                            payload={
                                "trace_id": str(trace.trace_id),
                                "instrument": trace.instrument,
                                "provider": provider,
                                "state": state,
                                "heartbeat_age_seconds": raw.get("heartbeat_age_seconds"),
                                "rate_limited": bool(raw.get("rate_limited")),
                                "detail": str(raw.get("detail") or ""),
                            },
                        )
                    )
            raw_errors = external.get("errors")
            if isinstance(raw_errors, (list, tuple)):
                for index, error in enumerate(raw_errors):
                    message = str(error).strip()
                    if not message:
                        continue
                    self._upsert_operational_event(
                        OperationalEvent(
                            event_id=f"trace:{trace.trace_id}:provider_error:{index}",
                            category=OperationalCategory.PROVIDER,
                            severity=OperationalSeverity.ERROR,
                            event_key="provider:runtime_error",
                            observed_at=trace.created_at,
                            payload={
                                "trace_id": str(trace.trace_id),
                                "instrument": trace.instrument,
                                "provider": "external_context",
                                "state": "error",
                                "error": message,
                            },
                        )
                    )

    def set_execution_readiness(
        self,
        account_id: str,
        ready: bool,
        *,
        broker_cursor: str | None = None,
        reason: str = "",
    ) -> None:
        if not account_id:
            raise ValueError("account_id is required")
        with self._lock, self._connection:
            self._connection.execute(
                """
                INSERT INTO execution_readiness(account_id, ready, broker_cursor, reason, updated_at)
                VALUES (?, ?, ?, ?, datetime('now'))
                ON CONFLICT(account_id) DO UPDATE SET
                    ready=excluded.ready,
                    broker_cursor=excluded.broker_cursor,
                    reason=excluded.reason,
                    updated_at=excluded.updated_at
                """,
                (account_id, 1 if ready else 0, broker_cursor, reason),
            )
            row = self._connection.execute(
                "SELECT updated_at FROM execution_readiness WHERE account_id = ?",
                (account_id,),
            ).fetchone()
        observed_at = _parse_sqlite_utc(str(row["updated_at"])) if row is not None else datetime.now(UTC)
        self._upsert_operational_event(
            OperationalEvent(
                event_id=f"readiness:{account_id}:{observed_at.isoformat()}",
                category=OperationalCategory.READINESS,
                severity=OperationalSeverity.INFO if ready else OperationalSeverity.CRITICAL,
                event_key=f"readiness:{account_id}:{'ready' if ready else 'not_ready'}",
                observed_at=observed_at,
                payload={
                    "account_id": account_id,
                    "ready": ready,
                    "broker_cursor": broker_cursor,
                    "reason": reason,
                },
            )
        )

    def execution_ready(self, account_id: str) -> bool:
        row = self._connection.execute(
            "SELECT ready FROM execution_readiness WHERE account_id = ?",
            (account_id,),
        ).fetchone()
        return bool(row["ready"]) if row is not None else False

    def execution_readiness(self, account_id: str) -> dict[str, object]:
        row = self._connection.execute(
            "SELECT ready, broker_cursor, reason, updated_at FROM execution_readiness WHERE account_id = ?",
            (account_id,),
        ).fetchone()
        if row is None:
            return {"account_id": account_id, "ready": False, "reason": "broker reconciliation has not established readiness"}
        return {
            "account_id": account_id,
            "ready": bool(row["ready"]),
            "broker_cursor": row["broker_cursor"],
            "reason": str(row["reason"]),
            "updated_at": str(row["updated_at"]),
        }

    def all_execution_readiness(self) -> list[dict[str, object]]:
        rows = self._connection.execute(
            "SELECT account_id, ready, broker_cursor, reason, updated_at FROM execution_readiness ORDER BY account_id"
        ).fetchall()
        return [
            {
                "account_id": str(row["account_id"]),
                "ready": bool(row["ready"]),
                "broker_cursor": row["broker_cursor"],
                "reason": str(row["reason"]),
                "updated_at": str(row["updated_at"]),
            }
            for row in rows
        ]

    def set_halt(self, name: str, reason: str) -> None:
        super().set_halt(name, reason)
        row = self._connection.execute(
            "SELECT created_at FROM system_halts WHERE name = ?",
            (name,),
        ).fetchone()
        observed_at = _parse_sqlite_utc(str(row["created_at"])) if row is not None else datetime.now(UTC)
        self._upsert_operational_event(
            OperationalEvent(
                event_id=f"halt:{name}:{observed_at.isoformat()}",
                category=OperationalCategory.HALT,
                severity=OperationalSeverity.CRITICAL,
                event_key=f"halt:{name}:set",
                observed_at=observed_at,
                payload={"name": name, "reason": reason, "active": True},
            )
        )

    def clear_halt(self, name: str) -> None:
        existing = self.get_halt(name)
        super().clear_halt(name)
        if existing is None:
            return
        observed_at = datetime.now(UTC)
        self._upsert_operational_event(
            OperationalEvent(
                event_id=f"halt:{name}:cleared:{observed_at.isoformat()}",
                category=OperationalCategory.HALT,
                severity=OperationalSeverity.INFO,
                event_key=f"halt:{name}:cleared",
                observed_at=observed_at,
                payload={"name": name, "reason": existing, "active": False},
            )
        )

    def active_halts(self) -> list[dict[str, object]]:
        rows = self._connection.execute(
            "SELECT name, reason, created_at FROM system_halts ORDER BY created_at, name"
        ).fetchall()
        return [
            {
                "name": str(row["name"]),
                "reason": str(row["reason"]),
                "created_at": str(row["created_at"]),
            }
            for row in rows
        ]

    def operational_events(
        self,
        *,
        limit: int = 1000,
        since: datetime | None = None,
        category: OperationalCategory | None = None,
        severity: OperationalSeverity | None = None,
    ) -> list[OperationalEvent]:
        if since is not None and since.tzinfo is None:
            raise ValueError("operational event since must be timezone-aware")
        conditions: list[str] = []
        params: list[object] = []
        if since is not None:
            conditions.append("observed_at >= ?")
            params.append(since.astimezone(UTC).isoformat())
        if category is not None:
            conditions.append("category = ?")
            params.append(category.value)
        if severity is not None:
            conditions.append("severity = ?")
            params.append(severity.value)
        sql = "SELECT event_id, category, severity, event_key, observed_at, payload_json FROM operational_events"
        if conditions:
            sql += " WHERE " + " AND ".join(conditions)
        sql += " ORDER BY observed_at DESC, event_id DESC LIMIT ?"
        params.append(max(1, min(limit, 10000)))
        rows = self._connection.execute(sql, tuple(params)).fetchall()
        return [
            OperationalEvent(
                event_id=str(row["event_id"]),
                category=OperationalCategory(str(row["category"])),
                severity=OperationalSeverity(str(row["severity"])),
                event_key=str(row["event_key"]),
                observed_at=datetime.fromisoformat(str(row["observed_at"])),
                payload=json.loads(str(row["payload_json"])),
            )
            for row in rows
        ]

    def _upsert_operational_event(self, event: OperationalEvent) -> None:
        with self._lock, self._connection:
            self._connection.execute(
                """
                INSERT INTO operational_events(event_id, category, severity, event_key, observed_at, payload_json)
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(event_id) DO UPDATE SET
                    category=excluded.category,
                    severity=excluded.severity,
                    event_key=excluded.event_key,
                    observed_at=excluded.observed_at,
                    payload_json=excluded.payload_json
                """,
                (
                    event.event_id,
                    event.category.value,
                    event.severity.value,
                    event.event_key,
                    event.observed_at.astimezone(UTC).isoformat(),
                    json.dumps(jsonable(event.payload), sort_keys=True),
                ),
            )

    def save_setup_instance(self, setup: SetupInstance) -> None:
        payload = json.dumps(jsonable(setup), sort_keys=True)
        with self._lock, self._connection:
            existing = self._connection.execute(
                "SELECT payload_json FROM setup_instances WHERE setup_id = ?", (setup.setup_id,)
            ).fetchone()
            if existing is not None and str(existing["payload_json"]) == payload:
                return
            self._connection.execute(
                """
                INSERT INTO setup_instances(
                    setup_id, instrument, setup_family, policy_version, state,
                    created_at, updated_at, anchor_id, payload_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(setup_id) DO UPDATE SET
                    state=excluded.state,
                    updated_at=excluded.updated_at,
                    payload_json=excluded.payload_json
                """,
                (
                    setup.setup_id,
                    setup.instrument,
                    setup.setup_family,
                    setup.policy_version,
                    setup.state.value,
                    setup.created_at.isoformat(),
                    setup.updated_at.isoformat(),
                    setup.anchor_id,
                    payload,
                ),
            )

    def save_setup_transition(self, transition: SetupTransition) -> None:
        payload = json.dumps(jsonable(transition), sort_keys=True)
        with self._lock, self._connection:
            existing = self._connection.execute(
                "SELECT payload_json FROM setup_transitions WHERE transition_id = ?",
                (transition.transition_id,),
            ).fetchone()
            if existing is not None:
                if str(existing["payload_json"]) != payload:
                    raise ValueError(f"setup transition {transition.transition_id} is immutable")
                return
            self._connection.execute(
                "INSERT INTO setup_transitions(transition_id, setup_id, available_at, payload_json) VALUES (?, ?, ?, ?)",
                (transition.transition_id, transition.setup_id, transition.available_at.isoformat(), payload),
            )

    def setup_transitions(self, setup_id: str) -> list[SetupTransition]:
        rows = self._connection.execute(
            "SELECT payload_json FROM setup_transitions WHERE setup_id = ? ORDER BY available_at, transition_id",
            (setup_id,),
        ).fetchall()
        transitions: list[SetupTransition] = []
        for row in rows:
            payload = json.loads(str(row["payload_json"]))
            transitions.append(
                SetupTransition(
                    transition_id=str(payload["transition_id"]),
                    setup_id=str(payload["setup_id"]),
                    from_state=SetupLifecycleState(str(payload["from_state"])),
                    to_state=SetupLifecycleState(str(payload["to_state"])),
                    available_at=datetime.fromisoformat(str(payload["available_at"])),
                    event_id=str(payload["event_id"]),
                    reason=str(payload["reason"]),
                )
            )
        return transitions

    def update_advanced_risk_state(
        self,
        *,
        account_id: str,
        nav: Decimal,
        realized_loss: bool = False,
        realized_win: bool = False,
        reserved_risk: Decimal | None = None,
        pending_risk: Decimal | None = None,
    ) -> dict[str, object]:
        if nav <= 0:
            raise ValueError("nav must be positive")
        row = self._connection.execute(
            "SELECT peak_nav, loss_streak, reserved_risk, pending_risk FROM advanced_risk_state WHERE account_id = ?",
            (account_id,),
        ).fetchone()
        peak_nav = max(nav, Decimal(str(row["peak_nav"])) if row is not None else nav)
        streak = int(row["loss_streak"]) if row is not None else 0
        if realized_loss:
            streak += 1
        elif realized_win:
            streak = 0
        reserved = Decimal(str(row["reserved_risk"])) if row is not None else Decimal("0")
        pending = Decimal(str(row["pending_risk"])) if row is not None else Decimal("0")
        if reserved_risk is not None:
            reserved = max(Decimal("0"), reserved_risk)
        if pending_risk is not None:
            pending = max(Decimal("0"), pending_risk)
        with self._lock, self._connection:
            self._connection.execute(
                """
                INSERT INTO advanced_risk_state(account_id, peak_nav, loss_streak, reserved_risk, pending_risk, updated_at)
                VALUES (?, ?, ?, ?, ?, datetime('now'))
                ON CONFLICT(account_id) DO UPDATE SET
                    peak_nav=excluded.peak_nav,
                    loss_streak=excluded.loss_streak,
                    reserved_risk=excluded.reserved_risk,
                    pending_risk=excluded.pending_risk,
                    updated_at=excluded.updated_at
                """,
                (account_id, str(peak_nav), streak, str(reserved), str(pending)),
            )
        return {
            "peak_nav": peak_nav,
            "loss_streak": streak,
            "reserved_risk": reserved,
            "pending_risk": pending,
            "drawdown_fraction": max(Decimal("0"), (peak_nav - nav) / peak_nav),
        }

    def advanced_risk_state(self, account_id: str, nav: Decimal) -> dict[str, object]:
        return self.update_advanced_risk_state(account_id=account_id, nav=nav)


def _parse_aware(value: str, *, fallback: datetime) -> datetime:
    if not value:
        return fallback
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return fallback
    return fallback if parsed.tzinfo is None else parsed


def _parse_sqlite_utc(value: str) -> datetime:
    parsed = datetime.fromisoformat(value)
    return parsed.replace(tzinfo=UTC) if parsed.tzinfo is None else parsed.astimezone(UTC)
