from __future__ import annotations

import json
import time
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from uuid import UUID

from forex_trader.domain.events import EventImportance, ScheduledMacroEvent
from forex_trader.domain.macro_history import MacroObservation
from forex_trader.domain.models import jsonable
from forex_trader.infrastructure.repository import SqliteDecisionRepository


def _sqlite_datetime(value: str) -> str:
    """Preserve SQLite datetime('now') semantics with offset-aware microsecond UTC."""
    if value == "now":
        return datetime.now(UTC).isoformat(timespec="microseconds")
    return value


class TradingRepository(SqliteDecisionRepository):
    """Safety-oriented repository used by the runtime control/execution path."""

    def __init__(self, path: str | Path = ":memory:") -> None:
        super().__init__(path)
        self._connection.create_function("datetime", 1, _sqlite_datetime)
        self._migrate_trading_state()

    def _migrate_trading_state(self) -> None:
        with self._connection:
            self._connection.execute(
                """
                CREATE TABLE IF NOT EXISTS system_halts (
                    name TEXT PRIMARY KEY,
                    reason TEXT NOT NULL,
                    created_at TEXT NOT NULL
                )
                """
            )
            self._connection.execute(
                """
                CREATE TABLE IF NOT EXISTS execution_locks (
                    account_id TEXT PRIMARY KEY,
                    owner TEXT NOT NULL,
                    expires_epoch REAL NOT NULL
                )
                """
            )
            self._connection.execute(
                """
                CREATE TABLE IF NOT EXISTS runtime_leases (
                    name TEXT PRIMARY KEY,
                    owner TEXT NOT NULL,
                    expires_epoch REAL NOT NULL
                )
                """
            )
            self._connection.execute(
                """
                CREATE TABLE IF NOT EXISTS scheduled_events (
                    event_id TEXT PRIMARY KEY,
                    currency TEXT NOT NULL,
                    scheduled_at TEXT NOT NULL,
                    payload_json TEXT NOT NULL
                )
                """
            )
            self._connection.execute(
                "CREATE INDEX IF NOT EXISTS idx_scheduled_events_time ON scheduled_events(scheduled_at, currency)"
            )
            self._connection.execute(
                """
                CREATE TABLE IF NOT EXISTS risk_day_state (
                    account_id TEXT NOT NULL,
                    trading_day TEXT NOT NULL,
                    worst_pl TEXT NOT NULL,
                    halted INTEGER NOT NULL,
                    updated_at TEXT NOT NULL,
                    PRIMARY KEY(account_id, trading_day)
                )
                """
            )

    def save_macro_observation(self, observation: MacroObservation) -> None:
        """Immutable insert: same ID is idempotent only when the payload is identical."""
        payload = json.dumps(jsonable(observation), sort_keys=True)
        observation_id = str(observation.observation_id)
        with self._lock, self._connection:
            existing = self._connection.execute(
                "SELECT payload_json FROM macro_observations WHERE observation_id = ?",
                (observation_id,),
            ).fetchone()
            if existing is not None:
                if str(existing["payload_json"]) != payload:
                    raise ValueError(f"macro observation {observation_id} is immutable")
                return
            self._connection.execute(
                """
                INSERT INTO macro_observations
                    (observation_id, kind, currency, available_at, payload_json)
                VALUES (?, ?, ?, ?, ?)
                """,
                (
                    observation_id,
                    observation.kind.value,
                    observation.currency,
                    observation.available_at.isoformat(),
                    payload,
                ),
            )

    def set_halt(self, name: str, reason: str) -> None:
        if not name or not reason:
            raise ValueError("halt name and reason are required")
        with self._lock, self._connection:
            self._connection.execute(
                """
                INSERT INTO system_halts(name, reason, created_at)
                VALUES (?, ?, datetime('now'))
                ON CONFLICT(name) DO UPDATE SET reason=excluded.reason, created_at=excluded.created_at
                """,
                (name, reason),
            )

    def get_halt(self, name: str) -> str | None:
        row = self._connection.execute("SELECT reason FROM system_halts WHERE name = ?", (name,)).fetchone()
        return None if row is None else str(row["reason"])

    def clear_halt(self, name: str) -> None:
        with self._lock, self._connection:
            self._connection.execute("DELETE FROM system_halts WHERE name = ?", (name,))

    def acquire_account_lock(self, account_id: str, owner: str, *, ttl_seconds: float = 30.0) -> bool:
        if not account_id or not owner or ttl_seconds <= 0:
            raise ValueError("account lock requires account_id, owner and positive TTL")
        now = time.time()
        with self._lock, self._connection:
            self._connection.execute("DELETE FROM execution_locks WHERE expires_epoch <= ?", (now,))
            cursor = self._connection.execute(
                "INSERT OR IGNORE INTO execution_locks(account_id, owner, expires_epoch) VALUES (?, ?, ?)",
                (account_id, owner, now + ttl_seconds),
            )
        return cursor.rowcount == 1

    def release_account_lock(self, account_id: str, owner: str) -> None:
        with self._lock, self._connection:
            self._connection.execute(
                "DELETE FROM execution_locks WHERE account_id = ? AND owner = ?",
                (account_id, owner),
            )

    def acquire_runtime_lease(
        self,
        name: str,
        owner: str,
        *,
        ttl_seconds: float,
    ) -> bool:
        if not name or not owner or ttl_seconds <= 0:
            raise ValueError("runtime lease requires name, owner and positive TTL")
        now = time.time()
        with self._lock, self._connection:
            self._connection.execute(
                "DELETE FROM runtime_leases WHERE expires_epoch <= ?",
                (now,),
            )
            cursor = self._connection.execute(
                "INSERT OR IGNORE INTO runtime_leases(name, owner, expires_epoch) VALUES (?, ?, ?)",
                (name, owner, now + ttl_seconds),
            )
        return cursor.rowcount == 1

    def renew_runtime_lease(
        self,
        name: str,
        owner: str,
        *,
        ttl_seconds: float,
    ) -> bool:
        if not name or not owner or ttl_seconds <= 0:
            raise ValueError("runtime lease requires name, owner and positive TTL")
        now = time.time()
        with self._lock, self._connection:
            cursor = self._connection.execute(
                """
                UPDATE runtime_leases
                SET expires_epoch = ?
                WHERE name = ? AND owner = ? AND expires_epoch > ?
                """,
                (now + ttl_seconds, name, owner, now),
            )
        return cursor.rowcount == 1

    def runtime_lease_owner(self, name: str) -> str | None:
        if not name:
            raise ValueError("runtime lease name is required")
        now = time.time()
        with self._lock, self._connection:
            self._connection.execute(
                "DELETE FROM runtime_leases WHERE name = ? AND expires_epoch <= ?",
                (name, now),
            )
            row = self._connection.execute(
                "SELECT owner FROM runtime_leases WHERE name = ?",
                (name,),
            ).fetchone()
        return None if row is None else str(row["owner"])

    def release_runtime_lease(self, name: str, owner: str) -> None:
        with self._lock, self._connection:
            self._connection.execute(
                "DELETE FROM runtime_leases WHERE name = ? AND owner = ?",
                (name, owner),
            )

    def observe_risk_day(
        self,
        *,
        account_id: str,
        trading_day: str,
        marked_pl: Decimal,
        loss_limit_amount: Decimal,
    ) -> bool:
        if loss_limit_amount <= 0:
            raise ValueError("loss_limit_amount must be positive")
        with self._lock, self._connection:
            row = self._connection.execute(
                "SELECT worst_pl, halted FROM risk_day_state WHERE account_id = ? AND trading_day = ?",
                (account_id, trading_day),
            ).fetchone()
            previous_worst = Decimal(str(row["worst_pl"])) if row is not None else Decimal("0")
            worst = min(previous_worst, marked_pl)
            halted = bool(row["halted"]) if row is not None else False
            halted = halted or -worst >= loss_limit_amount
            self._connection.execute(
                """
                INSERT INTO risk_day_state(account_id, trading_day, worst_pl, halted, updated_at)
                VALUES (?, ?, ?, ?, datetime('now'))
                ON CONFLICT(account_id, trading_day) DO UPDATE SET
                    worst_pl=excluded.worst_pl,
                    halted=excluded.halted,
                    updated_at=excluded.updated_at
                """,
                (account_id, trading_day, str(worst), 1 if halted else 0),
            )
        return halted

    def save_scheduled_event(self, event: ScheduledMacroEvent) -> None:
        payload_object = {
            "event_id": str(event.event_id),
            "currency": event.currency,
            "scheduled_at": event.scheduled_at.isoformat(),
            "name": event.name,
            "importance": event.importance.value,
            "source": event.source,
            "pre_blackout_seconds": int(event.pre_blackout.total_seconds()),
            "post_blackout_seconds": int(event.post_blackout.total_seconds()),
            "confidence": str(event.confidence),
        }
        payload = json.dumps(payload_object, sort_keys=True)
        with self._lock, self._connection:
            existing = self._connection.execute(
                "SELECT payload_json FROM scheduled_events WHERE event_id = ?", (str(event.event_id),)
            ).fetchone()
            if existing is not None:
                if str(existing["payload_json"]) != payload:
                    raise ValueError(f"scheduled event {event.event_id} is immutable")
                return
            self._connection.execute(
                "INSERT INTO scheduled_events(event_id, currency, scheduled_at, payload_json) VALUES (?, ?, ?, ?)",
                (str(event.event_id), event.currency, event.scheduled_at.isoformat(), payload),
            )

    def scheduled_events(self, *, start: datetime | None = None, end: datetime | None = None) -> list[ScheduledMacroEvent]:
        sql = "SELECT payload_json FROM scheduled_events"
        conditions: list[str] = []
        params: list[object] = []
        if start is not None:
            if start.tzinfo is None:
                raise ValueError("start must be timezone-aware")
            conditions.append("scheduled_at >= ?")
            params.append(start.isoformat())
        if end is not None:
            if end.tzinfo is None:
                raise ValueError("end must be timezone-aware")
            conditions.append("scheduled_at <= ?")
            params.append(end.isoformat())
        if conditions:
            sql += " WHERE " + " AND ".join(conditions)
        sql += " ORDER BY scheduled_at, event_id"
        rows = self._connection.execute(sql, tuple(params)).fetchall()
        return [_scheduled_from_json(json.loads(row["payload_json"])) for row in rows]

    def promotion_metrics(self):  # type: ignore[no-untyped-def]
        """Augment broker-P/L metrics with uncapped campaign coverage counters."""
        base = super().promotion_metrics()
        rows = self._connection.execute(
            "SELECT instrument, payload_json, created_at FROM decision_traces ORDER BY created_at"
        ).fetchall()
        decisions = len(rows)
        trade_candidates = 0
        submitted = 0
        rejected = 0
        unknown = 0
        active_days: set[str] = set()
        instruments: set[str] = set()
        sessions: set[str] = set()
        for row in rows:
            payload = json.loads(row["payload_json"])
            candidate = payload.get("candidate", {})
            if isinstance(candidate, dict) and candidate.get("disposition") == "trade":
                trade_candidates += 1
            active_days.add(str(row["created_at"])[:10])
            order = payload.get("order")
            if not isinstance(order, dict):
                continue
            submitted += 1
            instruments.add(str(row["instrument"]))
            status = str(order.get("status") or "")
            if status in {"rejected", "cancelled"}:
                rejected += 1
            if status in {"unknown", "reconciliation_required"}:
                unknown += 1
            metadata = payload.get("metadata")
            if isinstance(metadata, dict) and metadata.get("session_phase"):
                sessions.add(str(metadata["session_phase"]))
        halt_row = self._connection.execute("SELECT COUNT(*) AS count FROM system_halts").fetchone()
        unresolved_halts = int(halt_row["count"]) if halt_row is not None else 0
        return replace(
            base,
            decisions=decisions,
            trade_candidates=trade_candidates,
            submitted_orders=submitted,
            rejected_orders=rejected,
            unknown_orders=unknown,
            active_days=len(active_days),
            instruments_traded=len(instruments),
            sessions_traded=len(sessions),
            unresolved_halts=unresolved_halts,
        )


def _scheduled_from_json(payload: dict[str, object]) -> ScheduledMacroEvent:
    return ScheduledMacroEvent(
        event_id=UUID(str(payload["event_id"])),
        currency=str(payload["currency"]),
        scheduled_at=datetime.fromisoformat(str(payload["scheduled_at"])),
        name=str(payload["name"]),
        importance=EventImportance(str(payload.get("importance", "high"))),
        source=str(payload.get("source", "manual")),
        pre_blackout=timedelta(seconds=int(payload.get("pre_blackout_seconds", 900))),
        post_blackout=timedelta(seconds=int(payload.get("post_blackout_seconds", 300))),
        confidence=Decimal(str(payload.get("confidence", "1"))),
    )