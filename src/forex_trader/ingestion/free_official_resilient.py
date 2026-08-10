from __future__ import annotations

import csv
import html as html_module
import io
import json
import re
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from urllib.parse import urljoin

from forex_trader.ingestion.free_official import (
    BLS,
    BOJ,
    FED,
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
from forex_trader.ingestion.official_sources import (
    OFFICIAL_MACRO_SOURCES,
    SourceAuthority,
    SourceDescriptor,
)


_BLS_CPI_SERIES = "CUUR0000SA0"
_BLS_API_URL = f"https://api.bls.gov/publicAPI/v1/timeseries/data/{_BLS_CPI_SERIES}"
_BOJ_POLICY_TABLE_URL = "https://www.boj.or.jp/en/statistics/boj/other/discount/discount.htm"
_STATISTICS_JAPAN_CPI_URL = "https://www.stat.go.jp/data/cpi/sokuhou/tsuki/index-z.html"
_BIS_NZD_POLICY_URL = (
    "https://stats.bis.org/api/v2/data/dataflow/BIS/WS_CBPOL/1.0/M.NZ"
    "?startPeriod=2020-01&detail=dataonly&format=csvfile"
)
_STATS_NZ_CPI_TOPIC_URL = "https://www.stats.govt.nz/topics/consumers-price-index/"

BIS_SOURCE = SourceDescriptor(
    "bis",
    "Bank for International Settlements",
    SourceAuthority.OFFICIAL,
    frozenset({"stats.bis.org"}),
)
STATISTICS_JAPAN_SOURCE = SourceDescriptor(
    "statistics_japan",
    "Statistics Bureau of Japan",
    SourceAuthority.OFFICIAL,
    frozenset({"stat.go.jp"}),
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

    stats = client.fetch(STATISTICS_JAPAN_SOURCE, _STATISTICS_JAPAN_CPI_URL, retrieved_at=retrieved_at)
    inflation_value, inflation_reference = _statistics_japan_cpi(stats.body)
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
                inflation_value,
                None,
                False,
                inflation_reference,
            ),
        ),
    )


def _statistics_japan_cpi(body: bytes) -> tuple[Decimal, str]:
    candidates: list[str] = []
    for encoding in ("utf-8", "cp932", "shift_jis"):
        try:
            decoded = body.decode(encoding)
        except UnicodeDecodeError:
            continue
        visible = html_module.unescape(re.sub(r"<[^>]+>", " ", decoded))
        normalized = " ".join(visible.split())
        if normalized:
            candidates.append(normalized)
        if "前年同月比" in normalized and "総合指数" in normalized:
            break
    if not candidates:
        raise FreeOfficialSourceError("statistics_japan CPI page could not be decoded")
    text = candidates[-1]
    inflation = re.search(
        r"総合指数.*?前年同月比は\s*(-?\d+(?:\.\d+)?)\s*[％%]\s*の\s*(上昇|低下)",
        text,
    )
    if inflation is None:
        raise FreeOfficialSourceError("statistics_japan latest national CPI year-over-year indicator was not found")
    actual = Decimal(inflation.group(1))
    if inflation.group(2) == "低下":
        actual = -actual
    reference = re.search(r"全国\s+(\d{4})年(?:（[^）]+）)?\s*(\d{1,2})月分", text)
    if reference is None:
        raise FreeOfficialSourceError("statistics_japan CPI reference month was not found")
    return actual, f"{int(reference.group(1)):04d}-{int(reference.group(2)):02d}"


def _parse_flexible_date(value: str) -> date:
    cleaned = " ".join(value.replace(".", "").replace(",", " ").split())
    return _parse_date(cleaned)


def _fetch_nzd(client: OfficialWebClient, *, retrieved_at: datetime) -> OfficialCurrencySnapshot:
    policy = client.fetch(BIS_SOURCE, _BIS_NZD_POLICY_URL, retrieved_at=retrieved_at)
    policy_values = _bis_observations(policy.body)
    if not policy_values:
        raise FreeOfficialSourceError("bis New Zealand policy-rate series returned no observations")
    latest_policy = policy_values[-1]
    previous_policy = next(
        (item for item in reversed(policy_values[:-1]) if item[1] != latest_policy[1]),
        None,
    )

    topic = client.fetch(STATS_NZ_SOURCE, _STATS_NZ_CPI_TOPIC_URL, retrieved_at=retrieved_at)
    release_url = _latest_stats_nz_cpi_release_url(topic.url, html_document(topic).links)
    release = client.fetch(STATS_NZ_SOURCE, release_url, retrieved_at=retrieved_at)
    cpi_values = _stats_nz_cpi_values(html_document(release).rows)
    latest_cpi, previous_cpi = cpi_values[-1], cpi_values[-2]
    return OfficialCurrencySnapshot(
        "NZD",
        (policy, topic, release),
        (
            OfficialIndicatorEvidence(
                "bis",
                "central_bank_policy_rate_nz",
                "NZD",
                "policy",
                latest_policy[1],
                None if previous_policy is None else previous_policy[1],
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


def _bis_observations(body: bytes) -> list[tuple[str, Decimal]]:
    try:
        text = body.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise FreeOfficialSourceError("bis API returned invalid UTF-8 CSV") from exc
    reader = csv.DictReader(io.StringIO(text))
    observations: dict[str, Decimal] = {}
    for row in reader:
        period = (row.get("TIME_PERIOD") or "").strip()
        raw_value = (row.get("OBS_VALUE") or "").strip()
        if not period or raw_value in {"", ".", "NaN"}:
            continue
        try:
            observations[period] = Decimal(raw_value)
        except InvalidOperation:
            continue
    result = sorted(observations.items(), key=lambda item: item[0])
    if not result:
        raise FreeOfficialSourceError("bis API returned no usable observations")
    return result


def _latest_stats_nz_cpi_release_url(base_url: str, links: tuple[str, ...]) -> str:
    month_number = {"march": 3, "june": 6, "september": 9, "december": 12}
    candidates: list[tuple[tuple[int, int], str]] = []
    for href in links:
        absolute = urljoin(base_url, href).split("?", 1)[0].rstrip("/")
        match = re.search(
            r"/information-releases/consumers-price-index-(march|june|september|december)-(\d{4})-quarter$",
            absolute,
            flags=re.IGNORECASE,
        )
        if match is None:
            continue
        candidates.append(((int(match.group(2)), month_number[match.group(1).lower()]), absolute + "/"))
    if not candidates:
        raise FreeOfficialSourceError("stats_nz latest CPI release link was not found")
    candidates.sort(key=lambda item: item[0])
    return candidates[-1][1]


def _stats_nz_cpi_values(rows: tuple[tuple[str, ...], ...]) -> list[tuple[date, Decimal]]:
    month_number = {"mar": 3, "jun": 6, "sep": 9, "sept": 9, "dec": 12}
    values: dict[date, Decimal] = {}
    for row in rows:
        if len(row) < 3:
            continue
        match = re.fullmatch(r"(Mar|Jun|Sep|Sept|Dec)-(\d{2})", row[0].strip(), flags=re.IGNORECASE)
        if match is None:
            continue
        try:
            annual = Decimal(row[2].replace("%", "").strip())
        except InvalidOperation:
            continue
        when = date(2000 + int(match.group(2)), month_number[match.group(1).lower()], 1)
        values[when] = annual
    result = sorted(values.items(), key=lambda item: item[0])
    if len(result) < 2:
        raise FreeOfficialSourceError("stats_nz CPI table did not expose two annual observations")
    return result
