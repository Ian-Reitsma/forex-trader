from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from typing import Iterable, Mapping

from forex_trader.research.advanced import EventReplayScheduler, ReplayEvent


REPLAY_ARCHIVE_SCHEMA_VERSION = "1.0"
EXECUTABLE_QUOTE_EVENT = "executable_quote"


def canonical_payload_sha256(payload: Mapping[str, object]) -> str:
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def file_sha256(path: str | Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _aware(value: object, *, field: str) -> datetime:
    if not isinstance(value, str):
        raise ValueError(f"{field} must be an ISO-8601 timestamp string")
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError(f"{field} must be timezone-aware")
    return parsed


@dataclass(frozen=True, slots=True)
class ReplaySourceFile:
    path: str
    sha256: str
    event_types: tuple[str, ...]

    def __post_init__(self) -> None:
        if not self.path.strip():
            raise ValueError("replay source path is required")
        if Path(self.path).is_absolute():
            raise ValueError("replay source paths must be relative to the manifest")
        if len(self.sha256) != 64 or any(character not in "0123456789abcdef" for character in self.sha256.lower()):
            raise ValueError("replay source sha256 must be a 64-character hexadecimal digest")
        if not self.event_types:
            raise ValueError("replay source must declare at least one event type")
        if any(not item.strip() for item in self.event_types):
            raise ValueError("replay source event types must be non-empty")


@dataclass(frozen=True, slots=True)
class ReplayArchiveManifest:
    dataset_id: str
    created_at: datetime
    period_start: datetime
    period_end: datetime
    files: tuple[ReplaySourceFile, ...]
    required_event_types: tuple[str, ...]
    instruments: tuple[str, ...]
    schema_version: str = REPLAY_ARCHIVE_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if self.schema_version != REPLAY_ARCHIVE_SCHEMA_VERSION:
            raise ValueError(f"unsupported replay archive schema_version: {self.schema_version}")
        if not self.dataset_id.strip():
            raise ValueError("replay dataset_id is required")
        for value in (self.created_at, self.period_start, self.period_end):
            if value.tzinfo is None:
                raise ValueError("replay manifest timestamps must be timezone-aware")
        if self.period_end <= self.period_start:
            raise ValueError("replay period_end must be after period_start")
        if not self.files:
            raise ValueError("replay manifest must declare source files")
        if len({item.path for item in self.files}) != len(self.files):
            raise ValueError("replay manifest source paths must be unique")
        if not self.required_event_types:
            raise ValueError("replay manifest must declare required_event_types")
        normalized_instruments = tuple(item.upper() for item in self.instruments)
        if any("_" not in item for item in normalized_instruments):
            raise ValueError("replay manifest instruments must use BASE_QUOTE names")
        if len(set(normalized_instruments)) != len(normalized_instruments):
            raise ValueError("replay manifest instruments must be unique")

    @property
    def manifest_hash(self) -> str:
        payload = {
            "schema_version": self.schema_version,
            "dataset_id": self.dataset_id,
            "created_at": self.created_at.isoformat(),
            "period_start": self.period_start.isoformat(),
            "period_end": self.period_end.isoformat(),
            "files": [
                {"path": item.path, "sha256": item.sha256, "event_types": item.event_types}
                for item in self.files
            ],
            "required_event_types": self.required_event_types,
            "instruments": self.instruments,
        }
        return canonical_payload_sha256(payload)

    @classmethod
    def from_payload(cls, payload: Mapping[str, object]) -> "ReplayArchiveManifest":
        raw_files = payload.get("files")
        if not isinstance(raw_files, list):
            raise ValueError("replay manifest files must be a list")
        files: list[ReplaySourceFile] = []
        for raw in raw_files:
            if not isinstance(raw, dict):
                raise ValueError("replay manifest file entries must be objects")
            raw_event_types = raw.get("event_types")
            if not isinstance(raw_event_types, list):
                raise ValueError("replay source event_types must be a list")
            files.append(
                ReplaySourceFile(
                    path=str(raw["path"]),
                    sha256=str(raw["sha256"]).lower(),
                    event_types=tuple(str(item) for item in raw_event_types),
                )
            )
        required = payload.get("required_event_types")
        instruments = payload.get("instruments", [])
        if not isinstance(required, list) or not isinstance(instruments, list):
            raise ValueError("replay manifest required_event_types and instruments must be lists")
        return cls(
            dataset_id=str(payload["dataset_id"]),
            created_at=_aware(payload["created_at"], field="created_at"),
            period_start=_aware(payload["period_start"], field="period_start"),
            period_end=_aware(payload["period_end"], field="period_end"),
            files=tuple(files),
            required_event_types=tuple(str(item) for item in required),
            instruments=tuple(str(item).upper() for item in instruments),
            schema_version=str(payload.get("schema_version", "")),
        )


@dataclass(frozen=True, slots=True)
class ArchivedReplayRecord:
    event_id: str
    event_type: str
    occurred_at: datetime
    available_at: datetime
    provider: str
    channel: str
    provider_sequence: int
    payload: dict[str, object]
    payload_sha256: str

    def __post_init__(self) -> None:
        if not self.event_id.strip() or not self.event_type.strip():
            raise ValueError("replay record event_id and event_type are required")
        if self.occurred_at.tzinfo is None or self.available_at.tzinfo is None:
            raise ValueError("replay record timestamps must be timezone-aware")
        if not self.provider.strip() or not self.channel.strip():
            raise ValueError("replay record provider and channel are required")
        if self.provider_sequence < 0:
            raise ValueError("replay provider_sequence cannot be negative")
        expected = canonical_payload_sha256(self.payload)
        if self.payload_sha256.lower() != expected:
            raise ValueError(f"replay payload hash mismatch for {self.event_id}")

    @classmethod
    def from_payload(cls, payload: Mapping[str, object]) -> "ArchivedReplayRecord":
        raw_payload = payload.get("payload")
        if not isinstance(raw_payload, dict):
            raise ValueError("replay record payload must be an object")
        return cls(
            event_id=str(payload["event_id"]),
            event_type=str(payload["event_type"]),
            occurred_at=_aware(payload["occurred_at"], field="occurred_at"),
            available_at=_aware(payload["available_at"], field="available_at"),
            provider=str(payload["provider"]),
            channel=str(payload["channel"]),
            provider_sequence=int(str(payload["provider_sequence"])),
            payload={str(key): value for key, value in raw_payload.items()},
            payload_sha256=str(payload["payload_sha256"]).lower(),
        )

    def replay_event(self) -> ReplayEvent:
        return ReplayEvent(
            event_id=self.event_id,
            event_type=self.event_type,
            available_at=self.available_at,
            provider_sequence=self.provider_sequence,
            payload={
                **self.payload,
                "occurred_at": self.occurred_at.isoformat(),
                "provider": self.provider,
                "channel": self.channel,
                "payload_sha256": self.payload_sha256,
            },
        )


@dataclass(frozen=True, slots=True)
class ExecutableQuoteTick:
    event_id: str
    instrument: str
    bid: Decimal
    ask: Decimal
    occurred_at: datetime
    available_at: datetime
    provider: str
    channel: str
    provider_sequence: int
    tradeable: bool = True

    def __post_init__(self) -> None:
        if "_" not in self.instrument:
            raise ValueError("executable quote instrument must use BASE_QUOTE naming")
        if self.bid <= 0 or self.ask <= 0 or self.ask < self.bid:
            raise ValueError("executable quote requires positive bid <= ask")
        if self.occurred_at.tzinfo is None or self.available_at.tzinfo is None:
            raise ValueError("executable quote timestamps must be timezone-aware")

    @property
    def spread(self) -> Decimal:
        return self.ask - self.bid

    @property
    def mid(self) -> Decimal:
        return (self.bid + self.ask) / Decimal("2")

    @classmethod
    def from_record(cls, record: ArchivedReplayRecord) -> "ExecutableQuoteTick":
        if record.event_type != EXECUTABLE_QUOTE_EVENT:
            raise ValueError(f"record {record.event_id} is not an executable quote")
        payload = record.payload
        return cls(
            event_id=record.event_id,
            instrument=str(payload["instrument"]).upper(),
            bid=Decimal(str(payload["bid"])),
            ask=Decimal(str(payload["ask"])),
            occurred_at=record.occurred_at,
            available_at=record.available_at,
            provider=record.provider,
            channel=record.channel,
            provider_sequence=record.provider_sequence,
            tradeable=bool(payload.get("tradeable", True)),
        )


class PointInTimeExecutableQuoteBook:
    """Exact historical bid/ask lookup with no interpolation or future reach-forward."""

    def __init__(self, quotes: Iterable[ExecutableQuoteTick]) -> None:
        ordered = tuple(
            sorted(
                quotes,
                key=lambda item: (item.available_at, item.provider_sequence, item.event_id),
            )
        )
        self._by_instrument: dict[str, tuple[ExecutableQuoteTick, ...]] = {}
        buckets: dict[str, list[ExecutableQuoteTick]] = {}
        for quote in ordered:
            buckets.setdefault(quote.instrument.upper(), []).append(quote)
        self._by_instrument = {key: tuple(value) for key, value in buckets.items()}

    def quote_at(
        self,
        instrument: str,
        *,
        as_of: datetime,
        maximum_age_seconds: Decimal,
        require_tradeable: bool = True,
    ) -> ExecutableQuoteTick:
        if as_of.tzinfo is None:
            raise ValueError("quote lookup as_of must be timezone-aware")
        if maximum_age_seconds <= 0:
            raise ValueError("maximum_age_seconds must be positive")
        normalized = instrument.upper()
        candidates = self._by_instrument.get(normalized, ())
        eligible = [item for item in candidates if item.available_at <= as_of]
        if require_tradeable:
            eligible = [item for item in eligible if item.tradeable]
        if not eligible:
            raise LookupError(f"no point-in-time executable quote for {normalized} at {as_of.isoformat()}")
        latest = eligible[-1]
        age = Decimal(str((as_of - latest.available_at).total_seconds()))
        if age < 0 or age > maximum_age_seconds:
            raise LookupError(
                f"point-in-time executable quote for {normalized} is stale: {age}>{maximum_age_seconds} seconds"
            )
        return latest


@dataclass(frozen=True, slots=True)
class ReplayArchiveBundle:
    manifest: ReplayArchiveManifest
    records: tuple[ArchivedReplayRecord, ...]
    archive_hash: str

    @classmethod
    def load(cls, manifest_path: str | Path) -> "ReplayArchiveBundle":
        path = Path(manifest_path)
        raw_manifest = json.loads(path.read_text())
        if not isinstance(raw_manifest, dict):
            raise ValueError("replay manifest must be a JSON object")
        manifest = ReplayArchiveManifest.from_payload(raw_manifest)
        root = path.parent.resolve()
        records: list[ArchivedReplayRecord] = []
        event_ids: set[str] = set()
        sequences: set[tuple[str, str, int]] = set()
        observed_types: set[str] = set()
        digest_parts: list[str] = [manifest.manifest_hash]

        for source in manifest.files:
            source_path = (root / source.path).resolve()
            if not source_path.is_relative_to(root):
                raise ValueError(f"replay source escapes manifest directory: {source.path}")
            if not source_path.is_file():
                raise ValueError(f"replay source does not exist: {source.path}")
            checksum = file_sha256(source_path)
            if checksum.lower() != source.sha256.lower():
                raise ValueError(f"replay source checksum mismatch: {source.path}")
            digest_parts.append(f"{source.path}:{checksum}")
            for line_number, raw_line in enumerate(source_path.read_text().splitlines(), start=1):
                line = raw_line.strip()
                if not line:
                    continue
                try:
                    raw_record = json.loads(line)
                except json.JSONDecodeError as exc:
                    raise ValueError(f"{source.path}: invalid JSONL at line {line_number}") from exc
                if not isinstance(raw_record, dict):
                    raise ValueError(f"{source.path}: line {line_number} must be a JSON object")
                record = ArchivedReplayRecord.from_payload(raw_record)
                if record.event_type not in source.event_types:
                    raise ValueError(
                        f"{source.path}: event type {record.event_type} is not declared by the source manifest"
                    )
                if record.event_id in event_ids:
                    raise ValueError(f"duplicate replay event_id: {record.event_id}")
                sequence_key = (record.provider, record.channel, record.provider_sequence)
                if sequence_key in sequences:
                    raise ValueError(
                        "duplicate replay provider sequence: "
                        f"{record.provider}/{record.channel}/{record.provider_sequence}"
                    )
                if not manifest.period_start <= record.available_at <= manifest.period_end:
                    raise ValueError(f"replay event outside manifest availability period: {record.event_id}")
                if record.event_type == EXECUTABLE_QUOTE_EVENT:
                    quote = ExecutableQuoteTick.from_record(record)
                    if manifest.instruments and quote.instrument not in manifest.instruments:
                        raise ValueError(
                            f"replay quote instrument {quote.instrument} is outside the manifest universe"
                        )
                event_ids.add(record.event_id)
                sequences.add(sequence_key)
                observed_types.add(record.event_type)
                records.append(record)

        missing = set(manifest.required_event_types) - observed_types
        if missing:
            raise ValueError(f"replay archive is missing required event types: {', '.join(sorted(missing))}")
        ordered = tuple(
            sorted(records, key=lambda item: (item.available_at, item.provider_sequence, item.event_id))
        )
        archive_hash = hashlib.sha256("|".join(digest_parts).encode("utf-8")).hexdigest()
        return cls(manifest, ordered, archive_hash)

    def scheduler(self) -> EventReplayScheduler:
        return EventReplayScheduler(record.replay_event() for record in self.records)

    def events_until(self, as_of: datetime) -> tuple[ArchivedReplayRecord, ...]:
        if as_of.tzinfo is None:
            raise ValueError("replay cutoff must be timezone-aware")
        return tuple(record for record in self.records if record.available_at <= as_of)

    def quote_book(self) -> PointInTimeExecutableQuoteBook:
        return PointInTimeExecutableQuoteBook(
            ExecutableQuoteTick.from_record(record)
            for record in self.records
            if record.event_type == EXECUTABLE_QUOTE_EVENT
        )
