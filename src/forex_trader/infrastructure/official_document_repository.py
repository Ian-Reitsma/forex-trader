from __future__ import annotations

import sqlite3
from datetime import datetime
from pathlib import Path
from threading import Lock

from forex_trader.intelligence.official_documents import OfficialDocumentVersion


class OfficialDocumentRepository:
    """Append-only document-family lineage for source-backed extracted official text."""

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
                CREATE TABLE IF NOT EXISTS official_document_versions (
                    version_id TEXT PRIMARY KEY,
                    family_id TEXT NOT NULL,
                    source_id TEXT NOT NULL,
                    document_type TEXT NOT NULL,
                    institution TEXT NOT NULL,
                    currency TEXT NOT NULL,
                    discovery_id TEXT NOT NULL,
                    item_id TEXT NOT NULL,
                    document_url TEXT NOT NULL,
                    published_at TEXT NOT NULL,
                    available_at TEXT NOT NULL,
                    source_record_id TEXT NOT NULL,
                    source_payload_sha256 TEXT NOT NULL,
                    text_sha256 TEXT NOT NULL,
                    text TEXT NOT NULL,
                    predecessor_version_id TEXT
                )
                """
            )
            self._connection.execute(
                "CREATE INDEX IF NOT EXISTS idx_official_document_family_available "
                "ON official_document_versions(family_id, available_at DESC, version_id DESC)"
            )
            self._connection.execute(
                "CREATE INDEX IF NOT EXISTS idx_official_document_equivalent "
                "ON official_document_versions(family_id, discovery_id, source_payload_sha256, text_sha256)"
            )

    def append(self, version: OfficialDocumentVersion) -> bool:
        with self._lock, self._connection:
            existing = self._connection.execute(
                "SELECT 1 FROM official_document_versions WHERE version_id = ?",
                (version.version_id,),
            ).fetchone()
            if existing is not None:
                return False
            latest = self._latest_row(version.family_id)
            if latest is None:
                if version.predecessor_version_id is not None:
                    raise ValueError("first official document family version cannot reference a predecessor")
            else:
                latest_version = self._from_row(latest)
                if version.predecessor_version_id != latest_version.version_id:
                    raise ValueError("official document predecessor must reference the latest family version")
                if version.available_at <= latest_version.available_at:
                    raise ValueError("new official document version must become available after the latest family version")
            self._connection.execute(
                """
                INSERT INTO official_document_versions (
                    version_id, family_id, source_id, document_type, institution, currency,
                    discovery_id, item_id, document_url, published_at, available_at,
                    source_record_id, source_payload_sha256, text_sha256, text, predecessor_version_id
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    version.version_id,
                    version.family_id,
                    version.source_id,
                    version.document_type,
                    version.institution,
                    version.currency,
                    version.discovery_id,
                    version.item_id,
                    version.document_url,
                    version.published_at.isoformat(),
                    version.available_at.isoformat(),
                    version.source_record_id,
                    version.source_payload_sha256,
                    version.text_sha256,
                    version.text,
                    version.predecessor_version_id,
                ),
            )
        return True

    def get(self, version_id: str) -> OfficialDocumentVersion | None:
        row = self._connection.execute(
            "SELECT * FROM official_document_versions WHERE version_id = ?",
            (version_id,),
        ).fetchone()
        return self._from_row(row) if row is not None else None

    def latest(self, family_id: str) -> OfficialDocumentVersion | None:
        row = self._latest_row(family_id)
        return self._from_row(row) if row is not None else None

    def as_of(self, family_id: str, instant: datetime) -> OfficialDocumentVersion | None:
        if instant.tzinfo is None:
            raise ValueError("document as_of instant must be timezone-aware")
        row = self._connection.execute(
            """
            SELECT * FROM official_document_versions
            WHERE family_id = ? AND available_at <= ?
            ORDER BY available_at DESC, version_id DESC LIMIT 1
            """,
            (family_id, instant.isoformat()),
        ).fetchone()
        return self._from_row(row) if row is not None else None

    def equivalent(
        self,
        *,
        family_id: str,
        discovery_id: str,
        source_payload_sha256: str,
        text_sha256: str,
    ) -> OfficialDocumentVersion | None:
        row = self._connection.execute(
            """
            SELECT * FROM official_document_versions
            WHERE family_id = ? AND discovery_id = ? AND source_payload_sha256 = ? AND text_sha256 = ?
            ORDER BY available_at DESC, version_id DESC LIMIT 1
            """,
            (family_id, discovery_id, source_payload_sha256, text_sha256),
        ).fetchone()
        return self._from_row(row) if row is not None else None

    def _latest_row(self, family_id: str) -> sqlite3.Row | None:
        return self._connection.execute(
            """
            SELECT * FROM official_document_versions
            WHERE family_id = ?
            ORDER BY available_at DESC, version_id DESC LIMIT 1
            """,
            (family_id,),
        ).fetchone()

    @staticmethod
    def _from_row(row: sqlite3.Row) -> OfficialDocumentVersion:
        return OfficialDocumentVersion(
            family_id=row["family_id"],
            source_id=row["source_id"],
            document_type=row["document_type"],
            institution=row["institution"],
            currency=row["currency"],
            discovery_id=row["discovery_id"],
            item_id=row["item_id"],
            document_url=row["document_url"],
            published_at=datetime.fromisoformat(row["published_at"]),
            available_at=datetime.fromisoformat(row["available_at"]),
            source_record_id=row["source_record_id"],
            source_payload_sha256=row["source_payload_sha256"],
            text_sha256=row["text_sha256"],
            text=row["text"],
            predecessor_version_id=row["predecessor_version_id"],
        )
