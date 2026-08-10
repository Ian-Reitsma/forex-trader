from __future__ import annotations

import io
import json
import re
import zipfile
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal, InvalidOperation
from urllib.parse import urljoin
from xml.etree import ElementTree

import httpx

from forex_trader.ingestion.free_official import (
    BLS,
    BOJ,
    FED,
    RESERVE_BANK_NEW_ZEALAND_SOURCE,
    STATISTICS_JAPAN_SOURCE,
    FreeOfficialSourceError,
    OfficialCurrencySnapshot,
    OfficialIndicatorEvidence,
    OfficialWebClient,
    _date_digits_from_url,
    _fed_target_midpoint,
    _parse_date,
    fetch_currency as fetch_currency_legacy,
    html_document,
)
from forex_trader.ingestion.official_sources import RawSourcePayload, SourceAuthority, SourceDescriptor


_BLS_API_URL = "https://api.bls.gov/publicAPI/v2/timeseries/data/"
_BLS_CPI_SERIES = "CUUR0000SA0"
_BOJ_POLICY_TABLE_URL = "https://www.boj.or.jp/en/statistics/boj/other/discount/discount.htm"
_RBNZ_OCR_XLSX_URL = "https://rbnz.govt.nz/-/media/project/sites/rbnz/files/statistics/series/b/b2/hb2-daily-close.xlsx"
_RBNZ_CPI_XLSX_URL = "https://rbnz.govt.nz/-/media/project/sites/rbnz/files/statistics/series/m/m1/hm1.xlsx"


class ResilientOfficialWebClient(OfficialWebClient):
    """Official-only client with a constrained JSON POST for public statistical APIs."""

    def post_json(
        self,
        descriptor: SourceDescriptor,
        url: str,
        *,
        payload: dict[str, object],
        retrieved_at: datetime,
    ) -> RawSourcePayload:
        if descriptor.authority is not SourceAuthority.OFFICIAL:
            raise ValueError("free official client requires OFFICIAL source authority")
        if retrieved_at.tzinfo is None:
            raise ValueError("retrieved_at must be timezone-aware")
        if not descriptor.permits(url):
            raise ValueError(f"URL is not permitted for source {descriptor.source_id}: {url}")
        try:
            response = self._client.post(
                url,
                json=payload,
                headers={
                    "Accept": "application/json",
                    "Content-Type": "application/json",
                    "User-Agent": "forex-trader/free-official-macro",
                },
                timeout=self.timeout_seconds,
            )
        except httpx.HTTPError as exc:
            raise FreeOfficialSourceError(
                f"{descriptor.source_id} transport failure: {type(exc).__name__}"
            ) from exc
        if response.status_code != 200:
            raise FreeOfficialSourceError(f"{descriptor.source_id} returned HTTP {response.status_code}")
        final_url = str(response.url)
        if not descriptor.permits(final_url):
            raise FreeOfficialSourceError(f"{descriptor.source_id} response escaped approved publisher host")
        if len(response.content) > self.maximum_payload_bytes:
            raise FreeOfficialSourceError(f"{descriptor.source_id} payload exceeds configured maximum size")
        return RawSourcePayload.create(
            descriptor=descriptor,
            url=final_url,
            body=bytes(response.content),
            content_type=response.headers.get("content-type", "application/json").split(";", 1)[0],
            retrieved_at=retrieved_at.astimezone(UTC),
            published_at=retrieved_at.astimezone(UTC),
            available_at=retrieved_at.astimezone(UTC),
        )


def fetch_currency_resilient(
    currency: str,
    client: OfficialWebClient,
    *,
    retrieved_at: datetime,
) -> OfficialCurrencySnapshot:
    normalized = currency.upper()
    if normalized == "USD":
        if not isinstance(client, ResilientOfficialWebClient):
            raise TypeError("USD resilient adapter requires ResilientOfficialWebClient")
        return _fetch_usd(client, retrieved_at=retrieved_at)
    if normalized == "JPY":
        return _fetch_jpy(client, retrieved_at=retrieved_at)
    if normalized == "NZD":
        return _fetch_nzd(client, retrieved_at=retrieved_at)
    return fetch_currency_legacy(normalized, client, retrieved_at=retrieved_at)


def _fetch_usd(
    client: ResilientOfficialWebClient,
    *,
    retrieved_at: datetime,
) -> OfficialCurrencySnapshot:
    landing = client.fetch(
        FED,
        "https://www.federalreserve.gov/monetarypolicy.htm",
        retrieved_at=retrieved_at,
    )
    statement_urls: list[str] = []
    for href in html_document(landing).links:
        absolute = urljoin(landing.url, href)
        if re.search(r"/newsevents/pressreleases/monetary\d{8}a\.htm$", absolute):
            if absolute not in statement_urls:
                statement_urls.append(absolute)
    statement_urls.sort(key=_date_digits_from_url, reverse=True)
    if not statement_urls:
        raise FreeOfficialSourceError("federal_reserve latest FOMC statement link was not found")
    statements = tuple(client.fetch(FED, url, retrieved_at=retrieved_at) for url in statement_urls[:2])
    latest_rate = _fed_target_midpoint(html_document(statements[0]).text)
    previous_rate = (
        _fed_target_midpoint(html_document(statements[1]).text)
        if len(statements) > 1
        else None
    )

    api = client.post_json(
        BLS,
        _BLS_API_URL,
        payload={
            "seriesid": [_BLS_CPI_SERIES],
            "startyear": str(retrieved_at.year - 2),
            "endyear": str(retrieved_at.year),
        },
        retrieved_at=retrieved_at,
    )
    latest_cpi, previous_cpi, reference = _bls_cpi_annual_changes(api.body)
    return OfficialCurrencySnapshot(
        "USD",
        (landing, *statements, api),
        (
            OfficialIndicatorEvidence(
                "federal_reserve",
                "fed_funds_target_midpoint",
                "USD",
                "policy",
                latest_rate,
                previous_rate,
                True,
                _date_digits_from_url(statements[0].url),
            ),
            OfficialIndicatorEvidence(
                "bls",
                "cpi_u_12m_from_index",
                "USD",
                "inflation",
                latest_cpi,
                previous_cpi,
                False,
                reference,
            ),
        ),
    )


def _bls_cpi_annual_changes(body: bytes) -> tuple[Decimal, Decimal, str]:
    try:
        payload = json.loads(body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise FreeOfficialSourceError("bls API returned invalid JSON") from exc
    if not isinstance(payload, dict) or payload.get("status") != "REQUEST_SUCCEEDED":
        raise FreeOfficialSourceError("bls API request did not succeed")
    results = payload.get("Results")
    if not isinstance(results, dict):
        raise FreeOfficialSourceError("bls API response is missing Results")
    series = results.get("series")
    if not isinstance(series, list) or not series or not isinstance(series[0], dict):
        raise FreeOfficialSourceError("bls API response is missing CPI series")
    data = series[0].get("data")
    if not isinstance(data, list):
        raise FreeOfficialSourceError("bls API CPI series is missing data")
    values: dict[tuple[int, int], Decimal] = {}
    for item in data:
        if not isinstance(item, dict):
            continue
        period = item.get("period")
        year = item.get("year")
        value = item.get("value")
        if not isinstance(period, str) or re.fullmatch(r"M\d{2}", period) is None:
            continue
        if not isinstance(year, str) or not isinstance(value, str):
            continue
        month = int(period[1:])
        if not 1 <= month <= 12:
            continue
        try:
            values[(int(year), month)] = Decimal(value)
        except (InvalidOperation, ValueError):
            continue
    eligible = sorted(key for key in values if (key[0] - 1, key[1]) in values)
    if len(eligible) < 2:
        raise FreeOfficialSourceError("bls API did not expose enough CPI history for annual changes")
    latest_key = eligible[-1]
    previous_key = eligible[-2]
    latest = _percent_change(values[latest_key], values[(latest_key[0] - 1, latest_key[1])])
    previous = _percent_change(values[previous_key], values[(previous_key[0] - 1, previous_key[1])])
    return latest, previous, f"{latest_key[0]:04d}-{latest_key[1]:02d}"


def _percent_change(current: Decimal, prior: Decimal) -> Decimal:
    if prior == 0:
        raise FreeOfficialSourceError("official index prior value cannot be zero")
    return (current / prior - Decimal("1")) * Decimal("100")


def _fetch_jpy(client: OfficialWebClient, *, retrieved_at: datetime) -> OfficialCurrencySnapshot:
    policy = client.fetch(BOJ, _BOJ_POLICY_TABLE_URL, retrieved_at=retrieved_at)
    policy_rows: list[tuple[date, Decimal]] = []
    for row in html_document(policy).rows:
        if len(row) < 2:
            continue
        try:
            when = _parse_flexible_date(row[0])
            value = Decimal(row[-1].replace("%", "").strip())
        except (ValueError, InvalidOperation):
            continue
        if when.year >= 2001:
            policy_rows.append((when, value))
    policy_rows.sort(key=lambda item: item[0])
    if len(policy_rows) < 2:
        raise FreeOfficialSourceError("bank_of_japan basic loan rate table was not parsed")
    latest_rate = policy_rows[-1]
    previous_rate = policy_rows[-2]

    stats = client.fetch(
        STATISTICS_JAPAN_SOURCE,
        "https://www.stat.go.jp/english/",
        retrieved_at=retrieved_at,
    )
    text = html_document(stats).text
    inflation = re.search(
        r"Consumer Price Index\s+(-?\d+(?:\.\d+)?)%\s+([A-Za-z]+)\s+(\d{4})\s+change over the year",
        text,
        flags=re.IGNORECASE,
    )
    if inflation is None:
        raise FreeOfficialSourceError("statistics_japan latest CPI indicator was not found")
    return OfficialCurrencySnapshot(
        "JPY",
        (policy, stats),
        (
            OfficialIndicatorEvidence(
                "bank_of_japan",
                "basic_loan_rate",
                "JPY",
                "policy",
                latest_rate[1],
                previous_rate[1],
                True,
                latest_rate[0].isoformat(),
            ),
            OfficialIndicatorEvidence(
                "statistics_japan",
                "cpi_all_items_annual",
                "JPY",
                "inflation",
                Decimal(inflation.group(1)),
                None,
                False,
                f"{inflation.group(2)} {inflation.group(3)}",
            ),
        ),
    )


def _parse_flexible_date(value: str) -> date:
    cleaned = " ".join(value.replace(".", "").replace(",", " ").split())
    return _parse_date(cleaned)


def _fetch_nzd(client: OfficialWebClient, *, retrieved_at: datetime) -> OfficialCurrencySnapshot:
    ocr_payload = client.fetch(
        RESERVE_BANK_NEW_ZEALAND_SOURCE,
        _RBNZ_OCR_XLSX_URL,
        retrieved_at=retrieved_at,
    )
    cpi_payload = client.fetch(
        RESERVE_BANK_NEW_ZEALAND_SOURCE,
        _RBNZ_CPI_XLSX_URL,
        retrieved_at=retrieved_at,
    )
    ocr_rows = _xlsx_rows(ocr_payload.body)
    cpi_rows = _xlsx_rows(cpi_payload.body)
    ocr = _rbnz_ocr_values(ocr_rows)
    cpi = _rbnz_cpi_values(cpi_rows)
    if not ocr:
        raise FreeOfficialSourceError("rbnz B2 data file did not expose OCR values")
    if len(cpi) < 2:
        raise FreeOfficialSourceError("rbnz M1 data file did not expose two CPI observations")
    latest_ocr = ocr[-1]
    previous_distinct = next(
        (item for item in reversed(ocr[:-1]) if item[1] != latest_ocr[1]),
        None,
    )
    latest_cpi, previous_cpi = cpi[-1], cpi[-2]
    return OfficialCurrencySnapshot(
        "NZD",
        (ocr_payload, cpi_payload),
        (
            OfficialIndicatorEvidence(
                "reserve_bank_new_zealand",
                "official_cash_rate_b2",
                "NZD",
                "policy",
                latest_ocr[1],
                None if previous_distinct is None else previous_distinct[1],
                True,
                latest_ocr[0].isoformat(),
            ),
            OfficialIndicatorEvidence(
                "reserve_bank_new_zealand",
                "cpi_year_ended_m1",
                "NZD",
                "inflation",
                latest_cpi[1],
                previous_cpi[1],
                False,
                latest_cpi[0].isoformat(),
            ),
        ),
    )


def _xlsx_rows(body: bytes) -> tuple[tuple[str, ...], ...]:
    try:
        archive = zipfile.ZipFile(io.BytesIO(body))
    except (zipfile.BadZipFile, OSError) as exc:
        raise FreeOfficialSourceError("official XLSX payload is not a valid workbook") from exc
    with archive:
        shared = _xlsx_shared_strings(archive)
        rows: list[tuple[str, ...]] = []
        sheet_names = sorted(
            name for name in archive.namelist() if re.fullmatch(r"xl/worksheets/sheet\d+\.xml", name)
        )
        for sheet_name in sheet_names:
            try:
                root = ElementTree.fromstring(archive.read(sheet_name))
            except (ElementTree.ParseError, KeyError) as exc:
                raise FreeOfficialSourceError("official XLSX worksheet could not be parsed") from exc
            for row in root.findall(".//{*}row"):
                values: dict[int, str] = {}
                for cell in row.findall("{*}c"):
                    ref = cell.attrib.get("r", "")
                    column = _xlsx_column_index(ref)
                    if column is None:
                        continue
                    values[column] = _xlsx_cell_value(cell, shared)
                if values:
                    width = max(values) + 1
                    rows.append(tuple(values.get(index, "") for index in range(width)))
        return tuple(rows)


def _xlsx_shared_strings(archive: zipfile.ZipFile) -> tuple[str, ...]:
    try:
        body = archive.read("xl/sharedStrings.xml")
    except KeyError:
        return ()
    try:
        root = ElementTree.fromstring(body)
    except ElementTree.ParseError as exc:
        raise FreeOfficialSourceError("official XLSX shared strings could not be parsed") from exc
    result: list[str] = []
    for item in root.findall("{*}si"):
        result.append("".join(node.text or "" for node in item.findall(".//{*}t")))
    return tuple(result)


def _xlsx_column_index(reference: str) -> int | None:
    match = re.match(r"([A-Z]+)", reference.upper())
    if match is None:
        return None
    value = 0
    for char in match.group(1):
        value = value * 26 + (ord(char) - ord("A") + 1)
    return value - 1


def _xlsx_cell_value(cell: ElementTree.Element, shared: tuple[str, ...]) -> str:
    cell_type = cell.attrib.get("t", "")
    if cell_type == "inlineStr":
        return "".join(node.text or "" for node in cell.findall(".//{*}t"))
    node = cell.find("{*}v")
    if node is None or node.text is None:
        return ""
    raw = node.text.strip()
    if cell_type == "s":
        try:
            return shared[int(raw)]
        except (ValueError, IndexError):
            return ""
    return raw


def _rbnz_ocr_values(rows: tuple[tuple[str, ...], ...]) -> list[tuple[date, Decimal]]:
    header_row = -1
    ocr_column = -1
    for row_index, row in enumerate(rows):
        for column, value in enumerate(row):
            if "official cash rate" in value.lower():
                header_row = row_index
                ocr_column = column
                break
        if header_row >= 0:
            break
    if header_row < 0:
        return []
    values: list[tuple[date, Decimal]] = []
    for row in rows[header_row + 1 :]:
        if len(row) <= max(0, ocr_column):
            continue
        when = _excel_or_text_date(row[0])
        if when is None:
            continue
        try:
            rate = Decimal(row[ocr_column].strip())
        except (InvalidOperation, ValueError):
            continue
        values.append((when, rate))
    values.sort(key=lambda item: item[0])
    return values


def _rbnz_cpi_values(rows: tuple[tuple[str, ...], ...]) -> list[tuple[date, Decimal]]:
    values: list[tuple[date, Decimal]] = []
    for row in rows:
        if len(row) < 4:
            continue
        when = _excel_or_text_date(row[0])
        if when is None:
            continue
        try:
            annual = Decimal(row[3].strip())
        except (InvalidOperation, ValueError):
            continue
        if Decimal("-100") < annual < Decimal("100"):
            values.append((when, annual))
    values.sort(key=lambda item: item[0])
    deduplicated: dict[date, Decimal] = {}
    for when, value in values:
        deduplicated[when] = value
    return sorted(deduplicated.items(), key=lambda item: item[0])


def _excel_or_text_date(value: str) -> date | None:
    cleaned = value.strip()
    if not cleaned:
        return None
    try:
        serial = Decimal(cleaned)
    except InvalidOperation:
        serial = Decimal("0")
    if Decimal("20000") <= serial <= Decimal("100000"):
        return date(1899, 12, 30) + timedelta(days=int(serial))
    normalized = cleaned.replace("Sept", "Sep")
    for fmt in ("%d %b %Y", "%b %Y", "%B %Y", "%Y-%m-%d"):
        try:
            return datetime.strptime(normalized, fmt).date()
        except ValueError:
            continue
    return None
