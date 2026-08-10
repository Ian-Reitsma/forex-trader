from __future__ import annotations

import csv
import io
import json
import re
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from urllib.parse import urljoin

from forex_trader.ingestion.free_official import (
    BLS,
    FED,
    FreeOfficialSourceError,
    OfficialCurrencySnapshot,
    OfficialIndicatorEvidence,
    OfficialWebClient,
    _date_digits_from_url,
    _fed_target_midpoint,
    fetch_currency as fetch_currency_legacy,
    html_document,
)
from forex_trader.ingestion.official_sources import (
    OFFICIAL_MACRO_SOURCES,
    RawSourcePayload,
    SourceAuthority,
    SourceDescriptor,
)


_BLS_CPI_SERIES = "CUUR0000SA0"
_BLS_API_URL = f"https://api.bls.gov/publicAPI/v1/timeseries/data/{_BLS_CPI_SERIES}"
_BIS_JPY_POLICY_URL = (
    "https://stats.bis.org/api/v2/data/dataflow/BIS/WS_CBPOL/1.0/M.JP"
    "?startPeriod=2025-01&detail=dataonly&format=csvfile"
)
_BIS_JPY_CPI_URL = (
    "https://stats.bis.org/api/v2/data/dataflow/BIS/WS_LONG_CPI/1.0/M.JP.771"
    "?startPeriod=2025-01&detail=dataonly&format=csvfile"
)
_BIS_NZD_POLICY_URL = (
    "https://stats.bis.org/api/v2/data/dataflow/BIS/WS_CBPOL/1.0/M.NZ"
    "?startPeriod=2025-01&detail=dataonly&format=csvfile"
)

BIS_SOURCE = SourceDescriptor(
    "bis",
    "Bank for International Settlements",
    SourceAuthority.OFFICIAL,
    frozenset({"stats.bis.org"}),
)
STATS_NZ_SOURCE = OFFICIAL_MACRO_SOURCES["stats_nz"]


class ResilientOfficialWebClient(OfficialWebClient):
    """Official-only client used by resilient no-key source adapters."""


def fetch_currency_resilient(
    currency: str,
    client: OfficialWebClient,
    *,
    retrieved_at: datetime,
) -> OfficialCurrencySnapshot:
    normalized = currency.upper()
    if normalized == "USD":
        return _fetch_usd(client, retrieved_at=retrieved_at)
    if normalized == "JPY":
        return _fetch_jpy(client, retrieved_at=retrieved_at)
    if normalized == "NZD":
        return _fetch_nzd(client, retrieved_at=retrieved_at)
    return fetch_currency_legacy(normalized, client, retrieved_at=retrieved_at)


def _fetch_usd(
    client: OfficialWebClient,
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

    api = client.fetch(BLS, _BLS_API_URL, retrieved_at=retrieved_at)
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


def _bis_observations(body: bytes) -> list[tuple[str, Decimal]]:
    try:
        text = body.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise FreeOfficialSourceError("bis API returned invalid UTF-8 CSV") from exc
    reader = csv.DictReader(io.StringIO(text))
    values: dict[str, Decimal] = {}
    for row in reader:
        period = (row.get("TIME_PERIOD") or "").strip()
        raw_value = (row.get("OBS_VALUE") or "").strip()
        if not period or raw_value in {"", ".", "NaN"}:
            continue
        try:
            values[period] = Decimal(raw_value)
        except InvalidOperation:
            continue
    observations = sorted(values.items(), key=lambda item: item[0])
    if not observations:
        raise FreeOfficialSourceError("bis API returned no usable observations")
    return observations


def _fetch_jpy(
    client: OfficialWebClient,
    *,
    retrieved_at: datetime,
) -> OfficialCurrencySnapshot:
    policy_payload = client.fetch(BIS_SOURCE, _BIS_JPY_POLICY_URL, retrieved_at=retrieved_at)
    cpi_payload = client.fetch(BIS_SOURCE, _BIS_JPY_CPI_URL, retrieved_at=retrieved_at)
    policy = _bis_observations(policy_payload.body)
    cpi = _bis_observations(cpi_payload.body)
    if len(policy) < 2:
        raise FreeOfficialSourceError("bis Japan policy-rate series did not expose two observations")
    if len(cpi) < 2:
        raise FreeOfficialSourceError("bis Japan CPI series did not expose two observations")
    latest_policy, previous_policy = policy[-1], policy[-2]
    latest_cpi, previous_cpi = cpi[-1], cpi[-2]
    return OfficialCurrencySnapshot(
        "JPY",
        (policy_payload, cpi_payload),
        (
            OfficialIndicatorEvidence(
                "bis",
                "central_bank_policy_rate_jp",
                "JPY",
                "policy",
                latest_policy[1],
                previous_policy[1],
                True,
                latest_policy[0],
            ),
            OfficialIndicatorEvidence(
                "bis",
                "consumer_prices_yoy_jp",
                "JPY",
                "inflation",
                latest_cpi[1],
                previous_cpi[1],
                False,
                latest_cpi[0],
            ),
        ),
    )


def _stats_nz_release_candidates(retrieved_at: datetime) -> tuple[str, ...]:
    month_names = {3: "march", 6: "june", 9: "september", 12: "december"}
    candidates: list[str] = []
    for year in range(retrieved_at.year, retrieved_at.year - 3, -1):
        for month in (12, 9, 6, 3):
            if year == retrieved_at.year and month > retrieved_at.month:
                continue
            candidates.append(
                "https://www.stats.govt.nz/information-releases/"
                f"consumers-price-index-{month_names[month]}-{year}-quarter/"
            )
    return tuple(candidates)


def _parse_nz_quarter(value: str) -> date | None:
    match = re.fullmatch(r"(Mar|Jun|Sep|Sept|Dec)[- ](\d{2}|\d{4})", value.strip(), flags=re.IGNORECASE)
    if match is None:
        return None
    month = {"mar": 3, "jun": 6, "sep": 9, "sept": 9, "dec": 12}[match.group(1).lower()]
    raw_year = int(match.group(2))
    year = raw_year if raw_year >= 1000 else 2000 + raw_year
    return date(year, month, 1)


def _stats_nz_cpi_values(payload: RawSourcePayload) -> list[tuple[date, Decimal]]:
    rows = html_document(payload).rows
    header_index: int | None = None
    annual_column: int | None = None
    for index, row in enumerate(rows):
        if not row or row[0].strip().lower() != "quarter":
            continue
        for column, cell in enumerate(row):
            normalized = " ".join(cell.lower().split())
            if "cpi all groups" in normalized and "annual" in normalized:
                header_index = index
                annual_column = column
                break
        if header_index is not None:
            break
    if header_index is None or annual_column is None:
        raise FreeOfficialSourceError("stats_nz CPI annual-change table header was not found")

    values: list[tuple[date, Decimal]] = []
    for row in rows[header_index + 1 :]:
        if len(row) <= annual_column:
            continue
        period = _parse_nz_quarter(row[0])
        if period is None:
            if values:
                break
            continue
        try:
            annual = Decimal(row[annual_column].replace("%", "").strip())
        except InvalidOperation:
            continue
        values.append((period, annual))
    values.sort(key=lambda item: item[0])
    if len(values) < 2:
        raise FreeOfficialSourceError("stats_nz CPI table did not expose two annual observations")
    return values


def _fetch_latest_stats_nz_cpi(
    client: OfficialWebClient,
    *,
    retrieved_at: datetime,
) -> tuple[RawSourcePayload, list[tuple[date, Decimal]]]:
    for url in _stats_nz_release_candidates(retrieved_at):
        try:
            payload = client.fetch(STATS_NZ_SOURCE, url, retrieved_at=retrieved_at)
        except FreeOfficialSourceError as exc:
            if " returned HTTP 404" in str(exc):
                continue
            raise
        return payload, _stats_nz_cpi_values(payload)
    raise FreeOfficialSourceError("stats_nz current CPI release was not found")


def _fetch_nzd(
    client: OfficialWebClient,
    *,
    retrieved_at: datetime,
) -> OfficialCurrencySnapshot:
    policy_payload = client.fetch(BIS_SOURCE, _BIS_NZD_POLICY_URL, retrieved_at=retrieved_at)
    policy = _bis_observations(policy_payload.body)
    if len(policy) < 2:
        raise FreeOfficialSourceError("bis New Zealand policy-rate series did not expose two observations")
    cpi_payload, cpi = _fetch_latest_stats_nz_cpi(client, retrieved_at=retrieved_at)
    latest_policy, previous_policy = policy[-1], policy[-2]
    latest_cpi, previous_cpi = cpi[-1], cpi[-2]
    return OfficialCurrencySnapshot(
        "NZD",
        (policy_payload, cpi_payload),
        (
            OfficialIndicatorEvidence(
                "bis",
                "central_bank_policy_rate_nz",
                "NZD",
                "policy",
                latest_policy[1],
                previous_policy[1],
                True,
                latest_policy[0],
            ),
            OfficialIndicatorEvidence(
                "stats_nz",
                "cpi_all_groups_annual",
                "NZD",
                "inflation",
                latest_cpi[1],
                previous_cpi[1],
                False,
                latest_cpi[0].isoformat(),
            ),
        ),
    )
