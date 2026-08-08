from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal, InvalidOperation
from typing import Mapping

from forex_trader.ingestion.official_json import OfficialJsonPostClient, OfficialJsonQueryResponse
from forex_trader.ingestion.official_sources import OFFICIAL_MACRO_SOURCES


BLS_PUBLIC_DATA_V2_URL = "https://api.bls.gov/publicAPI/v2/timeseries/data/"
_SERIES_ID = re.compile(r"^[A-Z0-9_#-]+$")


@dataclass(frozen=True, slots=True)
class BlsQuery:
    series_ids: tuple[str, ...]
    start_year: int
    end_year: int

    def __post_init__(self) -> None:
        if not self.series_ids:
            raise ValueError("at least one BLS series ID is required")
        if len(self.series_ids) > 25:
            raise ValueError("unregistered BLS query is limited to 25 series IDs")
        if len(set(self.series_ids)) != len(self.series_ids):
            raise ValueError("BLS series IDs must be unique")
        if any(_SERIES_ID.fullmatch(item) is None for item in self.series_ids):
            raise ValueError("BLS series IDs must use uppercase letters, digits, underscore, dash or hash only")
        if self.start_year < 1900 or self.end_year < self.start_year:
            raise ValueError("BLS year range is invalid")
        if self.end_year - self.start_year > 9:
            raise ValueError("unregistered BLS query is conservatively limited to a 10-year inclusive range")

    def payload(self) -> dict[str, object]:
        return {
            "seriesid": list(self.series_ids),
            "startyear": str(self.start_year),
            "endyear": str(self.end_year),
        }


@dataclass(frozen=True, slots=True)
class BlsFootnote:
    code: str
    text: str


@dataclass(frozen=True, slots=True)
class BlsObservation:
    series_id: str
    year: int
    period: str
    period_name: str
    value: Decimal
    latest: bool
    footnotes: tuple[BlsFootnote, ...]


@dataclass(frozen=True, slots=True)
class BlsQueryResult:
    query: BlsQuery
    response: OfficialJsonQueryResponse
    observations: tuple[BlsObservation, ...]
    response_time_ms: int | None
    messages: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class BlsPublicDataAdapter:
    client: OfficialJsonPostClient

    def __post_init__(self) -> None:
        if self.client.descriptor.source_id != "bls":
            raise ValueError("BlsPublicDataAdapter requires the BLS official source descriptor")
        if self.client.descriptor != OFFICIAL_MACRO_SOURCES["bls"]:
            raise ValueError("BlsPublicDataAdapter requires the canonical BLS descriptor")

    def fetch(self, query: BlsQuery, *, retrieved_at: datetime) -> BlsQueryResult:
        response = self.client.query(BLS_PUBLIC_DATA_V2_URL, query.payload(), retrieved_at=retrieved_at)
        payload = response.json_object()
        status = str(payload.get("status", "")).strip()
        if status != "REQUEST_SUCCEEDED":
            messages = _messages(payload.get("message"))
            detail = "; ".join(messages) or status or "unknown BLS API failure"
            raise RuntimeError(f"BLS API request failed: {detail}")

        results = payload.get("Results")
        if not isinstance(results, Mapping):
            raise ValueError("BLS response Results must be an object")
        raw_series = results.get("series")
        if not isinstance(raw_series, list):
            raise ValueError("BLS response Results.series must be an array")

        requested = set(query.series_ids)
        returned: set[str] = set()
        observations: list[BlsObservation] = []
        for index, raw_item in enumerate(raw_series):
            if not isinstance(raw_item, Mapping):
                raise ValueError(f"BLS series[{index}] must be an object")
            series_id = str(raw_item.get("seriesID", "")).strip()
            if series_id not in requested:
                raise ValueError(f"BLS returned unrequested series ID {series_id!r}")
            if series_id in returned:
                raise ValueError(f"BLS returned duplicate series ID {series_id!r}")
            returned.add(series_id)
            data = raw_item.get("data")
            if not isinstance(data, list):
                raise ValueError(f"BLS series {series_id} data must be an array")
            for row_index, raw_row in enumerate(data):
                observations.append(_parse_observation(series_id, raw_row, row_index))

        missing = requested - returned
        if missing:
            raise ValueError(f"BLS response omitted requested series IDs: {sorted(missing)}")

        response_time_ms = _optional_response_time(payload.get("responseTime"))
        return BlsQueryResult(
            query=query,
            response=response,
            observations=tuple(observations),
            response_time_ms=response_time_ms,
            messages=_messages(payload.get("message")),
        )


def _parse_observation(series_id: str, raw_row: object, row_index: int) -> BlsObservation:
    if not isinstance(raw_row, Mapping):
        raise ValueError(f"BLS {series_id} data[{row_index}] must be an object")
    try:
        year = int(str(raw_row.get("year", "")))
    except ValueError as exc:
        raise ValueError(f"BLS {series_id} data[{row_index}] has invalid year") from exc
    period = str(raw_row.get("period", "")).strip()
    period_name = str(raw_row.get("periodName", "")).strip()
    if not period or not period_name:
        raise ValueError(f"BLS {series_id} data[{row_index}] is missing period identity")
    try:
        value = Decimal(str(raw_row.get("value", "")))
    except (InvalidOperation, ValueError) as exc:
        raise ValueError(f"BLS {series_id} data[{row_index}] has invalid numeric value") from exc

    latest_raw = str(raw_row.get("latest", "")).strip().lower()
    latest = latest_raw == "true"
    raw_footnotes = raw_row.get("footnotes", [])
    if not isinstance(raw_footnotes, list):
        raise ValueError(f"BLS {series_id} data[{row_index}] footnotes must be an array")
    footnotes: list[BlsFootnote] = []
    for footnote_index, item in enumerate(raw_footnotes):
        if not isinstance(item, Mapping):
            raise ValueError(
                f"BLS {series_id} data[{row_index}] footnotes[{footnote_index}] must be an object"
            )
        footnotes.append(BlsFootnote(str(item.get("code") or ""), str(item.get("text") or "")))
    return BlsObservation(series_id, year, period, period_name, value, latest, tuple(footnotes))


def _optional_response_time(value: object) -> int | None:
    if value is None or not str(value).strip():
        return None
    try:
        return int(str(value))
    except ValueError as exc:
        raise ValueError("BLS responseTime must be an integer") from exc


def _messages(value: object) -> tuple[str, ...]:
    if value is None:
        return ()
    if not isinstance(value, list):
        return (str(value),)
    return tuple(str(item) for item in value if str(item).strip())
