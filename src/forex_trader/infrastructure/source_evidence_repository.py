from __future__ import annotations

import sqlite3
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from threading import Lock

from forex_trader.domain.context import HealthState, ProviderHealth
from forex_trader.ingestion.official_sources import RawSourcePayload, SourceAuthority


class SourceEvidenceRepository:
    """Append-only local durability for macro source payloads and provider health evidence."""

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
                CREATE TABLE IF NOT EXISTS macro_source_payloads (
                    record_id TEXT PRIMARY KEY,
                    source_id TEXT NOT NULL,
                    publisher TEXT NOT NULL,
                    authority TEXT NOT NULL,
                    url TEXT NOT NULL,
                    content_type TEXT NOT NULL,
                    retrieved_at TEXT NOT NULL,
                    published_at TEXT NOT NULL,
                    available_at TEXT NOT NULL,
                    payload_sha256 TEXT NOT NULL,
                    body BLOB NOT NULL
                )
                """
            )
            self._connection.execute(
                "CREATE INDEX IF NOT EXISTS idx_macro_source_available "
                "ON macro_source_payloads(source_id, available_at)"
            )
            self._connection.execute(
                """
                CREATE TABLE IF NOT EXISTS macro_provider_health (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    provider TEXT NOT NULL,
                    state TEXT NOT NULL,
                    observed_at TEXT NOT NULL,
                    heartbeat_age_seconds TEXT NOT NULL,
                    rate_limited INTEGER NOT NULL,
                    detail TEXT NOT NULL
                )
                """
            )
            self._connection.execute(
                "CREATE INDEX IF NOT EXISTS idx_macro_provider_health "
                "ON macro_provider_health(provider, observed_at DESC, id DESC)"
            )

    def save_payload(self, payload: RawSourcePayload) -> bool:
        with self._lock, self._connection:
            cursor = self._connection.execute(
                """
                INSERT OR IGNORE INTO macro_source_payloads (
                    record_id, source_id, publisher, authority, url, content_type,
                    retrieved_at, published_at, available_at, payload_sha256, body
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    payload.record_id,
                    payload.source_id,
                    payload.publisher,
                    payload.authority.value,
                    payload.url,
                    payload.content_type,
                    payload.retrieved_at.isoformat(),
                    payload.published_at.isoformat(),
                    payload.available_at.isoformat(),
                    payload.payload_sha256,
                    payload.body,
                ),
            )
        return cursor.rowcount == 1

    def payload(self, record_id: str) -> RawSourcePayload | None:
        row = self._connection.execute(
            "SELECT * FROM macro_source_payloads WHERE record_id = ?",
            (record_id,),
        ).fetchone()
        if row is None:
            return None
        return RawSourcePayload(
            source_id=row["source_id"],
            publisher=row["publisher"],
            authority=SourceAuthority(row["authority"]),
            url=row["url"],
            content_type=row["content_type"],
            retrieved_at=datetime.fromisoformat(row["retrieved_at"]),
            published_at=datetime.fromisoformat(row["published_at"]),
            available_at=datetime.fromisoformat(row["available_at"]),
            payload_sha256=row["payload_sha256"],
            body=bytes(row["body"]),
        )

    def payloads_as_of(self, source_id: str, as_of: datetime) -> tuple[RawSourcePayload, ...]:
        if as_of.tzinfo is None:
            raise ValueError("as_of must be timezone-aware")
        rows = self._connection.execute(
            """
            SELECT record_id FROM macro_source_payloads
            WHERE source_id = ? AND available_at <= ?
            ORDER BY available_at, record_id
            """,
            (source_id, as_of.isoformat()),
        ).fetchall()
        results: list[RawSourcePayload] = []
        for row in rows:
            payload = self.payload(row["record_id"])
            if payload is not None:
                results.append(payload)
        return tuple(results)

    def save_health(self, health: ProviderHealth) -> None:
        with self._lock, self._connection:
            self._connection.execute(
                """
                INSERT INTO macro_provider_health (
                    provider, state, observed_at, heartbeat_age_seconds, rate_limited, detail
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    health.provider,
                    health.state.value,
                    health.observed_at.isoformat(),
                    str(health.heartbeat_age_seconds),
                    1 if health.rate_limited else 0,
                    health.detail,
                ),
            )

    def latest_health(
        self,
        provider: str,
        *,
        as_of: datetime,
        maximum_age_seconds: Decimal,
    ) -> ProviderHealth:
        if as_of.tzinfo is None:
            raise ValueError("as_of must be timezone-aware")
        if maximum_age_seconds < 0:
            raise ValueError("maximum_age_seconds cannot be negative")
        row = self._connection.execute(
            """
            SELECT provider, state, observed_at, heartbeat_age_seconds, rate_limited, detail
            FROM macro_provider_health
            WHERE provider = ? AND observed_at <= ?
            ORDER BY observed_at DESC, id DESC LIMIT 1
            """,
            (provider, as_of.isoformat()),
        ).fetchone()
        if row is None:
            return ProviderHealth(
                provider,
                HealthState.UNAVAILABLE,
                as_of,
                heartbeat_age_seconds=maximum_age_seconds + Decimal("1"),
                detail="no provider health observation available",
            )
        observed_at = datetime.fromisoformat(row["observed_at"])
        age = Decimal(str((as_of - observed_at).total_seconds()))
        if age > maximum_age_seconds:
            return ProviderHealth(
                provider,
                HealthState.UNAVAILABLE,
                as_of,
                heartbeat_age_seconds=age,
                rate_limited=bool(row["rate_limited"]),
                detail=f"stale provider health; last={observed_at.isoformat()}",
            )
        return ProviderHealth(
            provider,
            HealthState(row["state"]),
            observed_at,
            heartbeat_age_seconds=age,
            rate_limited=bool(row["rate_limited"]),
            detail=row["detail"],
        )
