from __future__ import annotations

import json
from datetime import datetime
from decimal import Decimal
from pathlib import Path

from forex_trader.domain.models import jsonable
from forex_trader.domain.setup_lifecycle import SetupInstance, SetupLifecycleState, SetupTransition
from forex_trader.infrastructure.trading_repository import TradingRepository


class AdvancedTradingRepository(TradingRepository):
    """Durable Phase A-D state layered on the existing safety repository."""

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
