from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from threading import Lock

from forex_trader.domain.models import DecisionTrace, jsonable


class SqliteDecisionRepository:
    def __init__(self, path: str | Path = ":memory:") -> None:
        self.path = str(path)
        self._lock = Lock()
        self._connection = sqlite3.connect(self.path, check_same_thread=False)
        self._connection.row_factory = sqlite3.Row
        self._migrate()

    def _migrate(self) -> None:
        with self._connection:
            self._connection.execute(
                """
                CREATE TABLE IF NOT EXISTS decision_traces (
                    trace_id TEXT PRIMARY KEY,
                    instrument TEXT NOT NULL,
                    disposition TEXT NOT NULL,
                    score TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    created_at TEXT NOT NULL
                )
                """
            )
            self._connection.execute(
                "CREATE INDEX IF NOT EXISTS idx_decisions_created ON decision_traces(created_at DESC)"
            )
            self._connection.execute(
                """
                CREATE TABLE IF NOT EXISTS execution_claims (
                    execution_key TEXT PRIMARY KEY,
                    claimed_at TEXT NOT NULL
                )
                """
            )

    def save_trace(self, trace: DecisionTrace) -> None:
        payload = jsonable(trace)
        with self._lock, self._connection:
            self._connection.execute(
                """
                INSERT OR REPLACE INTO decision_traces
                    (trace_id, instrument, disposition, score, payload_json, created_at)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    str(trace.trace_id),
                    trace.instrument,
                    trace.candidate.disposition.value,
                    str(trace.candidate.score),
                    json.dumps(payload, sort_keys=True),
                    trace.created_at.isoformat(),
                ),
            )

    def recent_traces(self, limit: int = 20) -> list[dict[str, object]]:
        rows = self._connection.execute(
            "SELECT payload_json FROM decision_traces ORDER BY created_at DESC LIMIT ?",
            (max(1, min(limit, 500)),),
        ).fetchall()
        return [json.loads(row["payload_json"]) for row in rows]


    def claim_execution(self, execution_key: str) -> bool:
        if not execution_key:
            raise ValueError("execution_key is required")
        with self._lock, self._connection:
            cursor = self._connection.execute(
                "INSERT OR IGNORE INTO execution_claims(execution_key, claimed_at) VALUES (?, datetime('now'))",
                (execution_key,),
            )
        return cursor.rowcount == 1

    def release_execution(self, execution_key: str) -> None:
        if not execution_key:
            return
        with self._lock, self._connection:
            self._connection.execute(
                "DELETE FROM execution_claims WHERE execution_key = ?",
                (execution_key,),
            )

    def close(self) -> None:
        self._connection.close()

    def __enter__(self) -> "SqliteDecisionRepository":
        return self

    def __exit__(self, exc_type: object, exc: object, traceback: object) -> None:
        self.close()

    def __del__(self) -> None:
        try:
            self._connection.close()
        except Exception:
            pass
