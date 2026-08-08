from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any, Iterable
from uuid import NAMESPACE_URL, UUID, uuid5

from forex_trader.domain.context import CrossAssetSignal, HealthState, ProviderHealth
from forex_trader.domain.events import EventImportance, ScheduledMacroEvent
from forex_trader.ingestion.providers import OrderFlowSnapshot
from forex_trader.intelligence.events import ConsensusSnapshot, NewsDocument, ReleaseActual, ReleaseMetadata


def _aware(value: object, *, field: str) -> datetime:
    if not isinstance(value, str):
        raise ValueError(f"{field} must be an ISO-8601 timestamp string")
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError(f"{field} must be timezone-aware")
    return parsed


def _decimal(value: object, *, field: str) -> Decimal:
    try:
        return Decimal(str(value))
    except Exception as exc:
        raise ValueError(f"{field} must be decimal-compatible") from exc


def _load_document(path: Path) -> object:
    if path.suffix.lower() == ".jsonl":
        rows: list[object] = []
        for line_number, raw_line in enumerate(path.read_text().splitlines(), start=1):
            line = raw_line.strip()
            if not line:
                continue
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError as exc:
                raise ValueError(f"{path}: invalid JSONL at line {line_number}") from exc
        return rows
    try:
        return json.loads(path.read_text())
    except json.JSONDecodeError as exc:
        raise ValueError(f"{path}: invalid JSON") from exc


def _rows(document: object, key: str) -> list[dict[str, Any]]:
    if isinstance(document, dict):
        payload = document.get(key, [])
    elif isinstance(document, list):
        tagged = [item for item in document if isinstance(item, dict) and "kind" in item]
        payload = [item for item in tagged if str(item.get("kind")) == key] if tagged else document
    else:
        payload = document
    if payload is None:
        return []
    if not isinstance(payload, list):
        raise ValueError(f"{key} payload must be a list")
    rows: list[dict[str, Any]] = []
    for item in payload:
        if not isinstance(item, dict):
            raise ValueError(f"{key} rows must be objects")
        rows.append(item)
    return rows


@dataclass(slots=True)
class _JsonProviderBase:
    path: Path
    provider_name: str
    maximum_heartbeat_age_seconds: Decimal

    def __init__(
        self,
        path: str | Path,
        *,
        provider_name: str,
        maximum_heartbeat_age_seconds: Decimal,
    ) -> None:
        self.path = Path(path)
        self.provider_name = provider_name
        self.maximum_heartbeat_age_seconds = maximum_heartbeat_age_seconds

    def _document(self) -> object:
        if not self.path.exists():
            raise FileNotFoundError(str(self.path))
        return _load_document(self.path)

    def _health_from_times(self, timestamps: Iterable[datetime]) -> ProviderHealth:
        observed_at = datetime.now(UTC)
        latest = max(timestamps, default=None)
        if latest is None:
            return ProviderHealth(
                self.provider_name,
                HealthState.UNAVAILABLE,
                observed_at,
                detail=f"{self.path}: no usable point-in-time records",
            )
        age = max(Decimal("0"), Decimal(str((observed_at - latest).total_seconds())))
        state = HealthState.HEALTHY if age <= self.maximum_heartbeat_age_seconds else HealthState.DEGRADED
        return ProviderHealth(
            self.provider_name,
            state,
            observed_at,
            heartbeat_age_seconds=age,
            detail=f"latest_record={latest.isoformat()} path={self.path}",
        )

    def _failure_health(self, exc: Exception) -> ProviderHealth:
        return ProviderHealth(
            self.provider_name,
            HealthState.UNAVAILABLE,
            datetime.now(UTC),
            detail=f"{type(exc).__name__}: {str(exc)[:240]}",
        )


class JsonEconomicCalendarProvider(_JsonProviderBase):
    """Point-in-time calendar/consensus adapter for vendor exports.

    The adapter never reconstructs consensus from future data. A consensus row is
    visible only after its own ``available_at`` timestamp and release actuals are
    independently timestamped.
    """

    def __init__(self, path: str | Path, *, provider_name: str = "economic_calendar_json") -> None:
        super().__init__(
            path,
            provider_name=provider_name,
            maximum_heartbeat_age_seconds=Decimal("21600"),
        )

    def consensus_snapshots(self, *, start: datetime, end: datetime) -> tuple[ConsensusSnapshot, ...]:
        rows = _rows(self._document(), "consensus")
        snapshots = [
            ConsensusSnapshot(
                indicator=str(row["indicator"]),
                currency=str(row["currency"]).upper(),
                consensus=_decimal(row["consensus"], field="consensus"),
                previous_known=_decimal(row["previous_known"], field="previous_known"),
                available_at=_aware(row["available_at"], field="available_at"),
                source=str(row.get("source") or self.provider_name),
            )
            for row in rows
        ]
        return tuple(
            sorted(
                (item for item in snapshots if start <= item.available_at <= end),
                key=lambda item: (item.available_at, item.currency, item.indicator, item.source),
            )
        )

    def release_actuals(self, *, start: datetime, end: datetime) -> tuple[ReleaseActual, ...]:
        rows = _rows(self._document(), "actuals")
        actuals = [
            ReleaseActual(
                indicator=str(row["indicator"]),
                currency=str(row["currency"]).upper(),
                actual=_decimal(row["actual"], field="actual"),
                revised_previous=_decimal(row["revised_previous"], field="revised_previous"),
                available_at=_aware(row["available_at"], field="available_at"),
                source=str(row.get("source") or self.provider_name),
            )
            for row in rows
        ]
        return tuple(
            sorted(
                (item for item in actuals if start <= item.available_at <= end),
                key=lambda item: (item.available_at, item.currency, item.indicator, item.source),
            )
        )

    def release_metadata(self) -> tuple[ReleaseMetadata, ...]:
        rows = _rows(self._document(), "metadata")
        return tuple(
            ReleaseMetadata(
                indicator=str(row["indicator"]),
                currency=str(row["currency"]).upper(),
                directionality=_decimal(row["directionality"], field="directionality"),
                unit=str(row.get("unit", "")),
                seasonal_adjustment=str(row.get("seasonal_adjustment", "")),
            )
            for row in rows
        )

    def scheduled_events(
        self,
        *,
        start: datetime,
        end: datetime,
        as_of: datetime,
    ) -> tuple[ScheduledMacroEvent, ...]:
        events: list[ScheduledMacroEvent] = []
        for row in _rows(self._document(), "scheduled"):
            scheduled_at = _aware(row["scheduled_at"], field="scheduled_at")
            available_at = _aware(row.get("available_at", row["scheduled_at"]), field="available_at")
            if available_at > as_of or not start <= scheduled_at <= end:
                continue
            source = str(row.get("source") or self.provider_name)
            raw_event_id = str(
                row.get("event_id")
                or f"{row['currency']}:{row['name']}:{scheduled_at.isoformat()}"
            )
            try:
                event_id = UUID(raw_event_id)
            except ValueError:
                event_id = uuid5(NAMESPACE_URL, f"{source}:{raw_event_id}")
            events.append(
                ScheduledMacroEvent(
                    event_id=event_id,
                    currency=str(row["currency"]).upper(),
                    scheduled_at=scheduled_at,
                    name=str(row["name"]),
                    importance=EventImportance(str(row.get("importance", "high")).lower()),
                    source=source,
                    pre_blackout=timedelta(minutes=int(row.get("pre_blackout_minutes", 15))),
                    post_blackout=timedelta(minutes=int(row.get("post_blackout_minutes", 5))),
                    confidence=_decimal(row.get("confidence", "1"), field="confidence"),
                )
            )
        return tuple(sorted(events, key=lambda item: (item.scheduled_at, str(item.event_id))))

    def health(self) -> ProviderHealth:
        try:
            document = self._document()
            timestamps = [
                _aware(row["available_at"], field="available_at")
                for key in ("consensus", "actuals", "scheduled")
                for row in _rows(document, key)
                if "available_at" in row
            ]
            return self._health_from_times(timestamps)
        except Exception as exc:
            return self._failure_health(exc)


class JsonNewsProvider(_JsonProviderBase):
    """Runtime news adapter for a normalized licensed/provider export."""

    def __init__(self, path: str | Path, *, provider_name: str = "news_json") -> None:
        super().__init__(
            path,
            provider_name=provider_name,
            maximum_heartbeat_age_seconds=Decimal("900"),
        )

    def news(self, *, start: datetime, end: datetime) -> tuple[NewsDocument, ...]:
        rows = _rows(self._document(), "news")
        documents = [
            NewsDocument(
                document_id=str(row["document_id"]),
                headline=str(row["headline"]),
                body=str(row.get("body", "")),
                source=str(row.get("source") or self.provider_name),
                published_at=_aware(row["published_at"], field="published_at"),
                received_at=_aware(row["received_at"], field="received_at"),
                authority=_decimal(row.get("authority", "0.5"), field="authority"),
            )
            for row in rows
        ]
        # received_at is the PIT availability boundary. Publication time alone is
        # insufficient because delayed provider delivery would otherwise leak data.
        return tuple(
            sorted(
                (item for item in documents if start <= item.received_at <= end),
                key=lambda item: (item.received_at, item.published_at, item.document_id),
            )
        )

    def health(self) -> ProviderHealth:
        try:
            document = self._document()
            timestamps = [_aware(row["received_at"], field="received_at") for row in _rows(document, "news")]
            return self._health_from_times(timestamps)
        except Exception as exc:
            return self._failure_health(exc)


class JsonCrossAssetProvider(_JsonProviderBase):
    """Point-in-time cross-asset signal adapter.

    Rows must already be normalized to the FX pair orientation: positive direction
    supports a long in ``instrument`` and negative direction supports a short.
    """

    def __init__(self, path: str | Path, *, provider_name: str = "cross_asset_json") -> None:
        super().__init__(
            path,
            provider_name=provider_name,
            maximum_heartbeat_age_seconds=Decimal("300"),
        )

    def signals(self, instrument: str, *, as_of: datetime) -> tuple[CrossAssetSignal, ...]:
        normalized = instrument.upper()
        rows = _rows(self._document(), "cross_asset")
        candidates: list[CrossAssetSignal] = []
        for row in rows:
            if str(row["instrument"]).upper() != normalized:
                continue
            observed_at = _aware(row["observed_at"], field="observed_at")
            if observed_at > as_of:
                continue
            candidates.append(
                CrossAssetSignal(
                    name=str(row["name"]),
                    direction=_decimal(row["direction"], field="direction"),
                    confidence=_decimal(row["confidence"], field="confidence"),
                    source=str(row.get("source") or self.provider_name),
                    observed_at=observed_at,
                )
            )
        latest: dict[tuple[str, str], CrossAssetSignal] = {}
        for item in candidates:
            key = (item.name, item.source)
            previous = latest.get(key)
            if previous is None or item.observed_at > previous.observed_at:
                latest[key] = item
        return tuple(sorted(latest.values(), key=lambda item: (item.name, item.source, item.observed_at)))

    def health(self) -> ProviderHealth:
        try:
            document = self._document()
            timestamps = [_aware(row["observed_at"], field="observed_at") for row in _rows(document, "cross_asset")]
            return self._health_from_times(timestamps)
        except Exception as exc:
            return self._failure_health(exc)


class JsonOrderFlowProvider(_JsonProviderBase):
    """Centralized-flow adapter for normalized futures/venue snapshots.

    Raw delta/CVD may be carried for research, while ``directional_pressure`` is
    the explicitly normalized [-1, 1] value eligible for confirmation logic.
    Stale snapshots fail closed and return ``None``.
    """

    def __init__(
        self,
        path: str | Path,
        *,
        provider_name: str = "institutional_flow_json",
        maximum_snapshot_age_seconds: Decimal = Decimal("60"),
    ) -> None:
        super().__init__(
            path,
            provider_name=provider_name,
            maximum_heartbeat_age_seconds=maximum_snapshot_age_seconds,
        )
        if maximum_snapshot_age_seconds <= 0:
            raise ValueError("maximum_snapshot_age_seconds must be positive")
        self.maximum_snapshot_age_seconds = maximum_snapshot_age_seconds

    def snapshot(self, instrument: str, *, as_of: datetime) -> OrderFlowSnapshot | None:
        normalized = instrument.upper()
        snapshots: list[OrderFlowSnapshot] = []
        for row in _rows(self._document(), "order_flow"):
            if str(row["instrument"]).upper() != normalized:
                continue
            observed_at = _aware(row["observed_at"], field="observed_at")
            if observed_at > as_of:
                continue
            snapshots.append(
                OrderFlowSnapshot(
                    instrument=normalized,
                    observed_at=observed_at,
                    source=str(row.get("source") or self.provider_name),
                    delta=None if row.get("delta") is None else _decimal(row["delta"], field="delta"),
                    cumulative_delta=None
                    if row.get("cumulative_delta") is None
                    else _decimal(row["cumulative_delta"], field="cumulative_delta"),
                    vwap=None if row.get("vwap") is None else _decimal(row["vwap"], field="vwap"),
                    point_of_control=None
                    if row.get("point_of_control") is None
                    else _decimal(row["point_of_control"], field="point_of_control"),
                    volume_expansion=None
                    if row.get("volume_expansion") is None
                    else _decimal(row["volume_expansion"], field="volume_expansion"),
                    absorption=None
                    if row.get("absorption") is None
                    else _decimal(row["absorption"], field="absorption"),
                    depth_imbalance=None
                    if row.get("depth_imbalance") is None
                    else _decimal(row["depth_imbalance"], field="depth_imbalance"),
                    directional_pressure=None
                    if row.get("directional_pressure") is None
                    else _decimal(row["directional_pressure"], field="directional_pressure"),
                    confidence=_decimal(row.get("confidence", "0"), field="confidence"),
                )
            )
        if not snapshots:
            return None
        latest = max(snapshots, key=lambda item: item.observed_at)
        age = Decimal(str((as_of - latest.observed_at).total_seconds()))
        if age < 0 or age > self.maximum_snapshot_age_seconds:
            return None
        return latest

    def health(self) -> ProviderHealth:
        try:
            document = self._document()
            timestamps = [_aware(row["observed_at"], field="observed_at") for row in _rows(document, "order_flow")]
            return self._health_from_times(timestamps)
        except Exception as exc:
            return self._failure_health(exc)
