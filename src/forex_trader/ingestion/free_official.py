from __future__ import annotations

import csv
import hashlib
import io
import re
from dataclasses import dataclass
from datetime import UTC, date, datetime
from decimal import Decimal, InvalidOperation
from html.parser import HTMLParser
from typing import Callable, Iterable
from urllib.parse import urljoin

import httpx

from forex_trader.ingestion.official_sources import (
    OFFICIAL_MACRO_SOURCES,
    RawSourcePayload,
    SourceAuthority,
    SourceDescriptor,
)


BANK_OF_CANADA_SOURCE = SourceDescriptor(
    "bank_of_canada",
    "Bank of Canada",
    SourceAuthority.OFFICIAL,
    frozenset({"bankofcanada.ca"}),
)
RESERVE_BANK_AUSTRALIA_SOURCE = SourceDescriptor(
    "reserve_bank_australia",
    "Reserve Bank of Australia",
    SourceAuthority.OFFICIAL,
    frozenset({"rba.gov.au"}),
)
RESERVE_BANK_NEW_ZEALAND_SOURCE = SourceDescriptor(
    "reserve_bank_new_zealand",
    "Reserve Bank of New Zealand",
    SourceAuthority.OFFICIAL,
    frozenset({"rbnz.govt.nz"}),
)
SWISS_NATIONAL_BANK_SOURCE = SourceDescriptor(
    "swiss_national_bank",
    "Swiss National Bank",
    SourceAuthority.OFFICIAL,
    frozenset({"snb.ch"}),
)
OFFICE_NATIONAL_STATISTICS_SOURCE = SourceDescriptor(
    "office_national_statistics",
    "Office for National Statistics",
    SourceAuthority.OFFICIAL,
    frozenset({"ons.gov.uk"}),
)
STATISTICS_JAPAN_SOURCE = SourceDescriptor(
    "statistics_japan",
    "Statistics Bureau of Japan",
    SourceAuthority.OFFICIAL,
    frozenset({"stat.go.jp"}),
)
ECB_DATA_SOURCE = SourceDescriptor(
    "ecb",
    "European Central Bank",
    SourceAuthority.OFFICIAL,
    frozenset({"ecb.europa.eu", "data.ecb.europa.eu", "data-api.ecb.europa.eu"}),
)

FED = OFFICIAL_MACRO_SOURCES["federal_reserve"]
BLS = OFFICIAL_MACRO_SOURCES["bls"]
BOE = OFFICIAL_MACRO_SOURCES["bank_of_england"]
BOJ = OFFICIAL_MACRO_SOURCES["bank_of_japan"]


class FreeOfficialSourceError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class OfficialIndicatorEvidence:
    source_id: str
    series_id: str
    currency: str
    category: str
    actual: Decimal
    previous: Decimal | None
    higher_is_positive: bool
    reference: str
    importance: Decimal = Decimal("1")

    def __post_init__(self) -> None:
        if not self.source_id.strip() or not self.series_id.strip() or not self.reference.strip():
            raise ValueError("official indicator identity fields are required")
        if len(self.currency.strip()) != 3:
            raise ValueError("currency must be a three-letter code")
        if not Decimal("0") < self.importance <= Decimal("1"):
            raise ValueError("importance must be in (0,1]")

    @property
    def source_key(self) -> str:
        identity = "|".join(
            (
                self.source_id,
                self.series_id,
                self.currency.upper(),
                self.category.lower(),
                self.reference,
                str(self.actual),
                "" if self.previous is None else str(self.previous),
            )
        )
        digest = hashlib.sha256(identity.encode("utf-8")).hexdigest()[:24]
        return f"official:{self.source_id}:{self.series_id}:{digest}"


@dataclass(frozen=True, slots=True)
class OfficialCurrencySnapshot:
    currency: str
    payloads: tuple[RawSourcePayload, ...]
    indicators: tuple[OfficialIndicatorEvidence, ...]

    def __post_init__(self) -> None:
        if len(self.currency.strip()) != 3:
            raise ValueError("currency must be a three-letter code")
        if any(item.currency.upper() != self.currency.upper() for item in self.indicators):
            raise ValueError("snapshot indicator currency mismatch")
        if any(payload.authority is not SourceAuthority.OFFICIAL for payload in self.payloads):
            raise ValueError("free official snapshots may contain only OFFICIAL payloads")


@dataclass(frozen=True, slots=True)
class HtmlDocument:
    text: str
    links: tuple[str, ...]
    rows: tuple[tuple[str, ...], ...]


class _DocumentParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.text_parts: list[str] = []
        self.links: list[str] = []
        self.rows: list[tuple[str, ...]] = []
        self._row: list[str] | None = None
        self._cell_parts: list[str] | None = None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        lowered = tag.lower()
        if lowered == "a":
            for name, value in attrs:
                if name.lower() == "href" and value:
                    self.links.append(value)
                    break
        elif lowered == "tr":
            self._row = []
        elif lowered in {"td", "th"} and self._row is not None:
            self._cell_parts = []

    def handle_data(self, data: str) -> None:
        value = " ".join(data.split())
        if not value:
            return
        self.text_parts.append(value)
        if self._cell_parts is not None:
            self._cell_parts.append(value)

    def handle_endtag(self, tag: str) -> None:
        lowered = tag.lower()
        if lowered in {"td", "th"} and self._cell_parts is not None and self._row is not None:
            self._row.append(" ".join(self._cell_parts).strip())
            self._cell_parts = None
        elif lowered == "tr" and self._row is not None:
            if any(cell for cell in self._row):
                self.rows.append(tuple(self._row))
            self._row = None
            self._cell_parts = None


class OfficialWebClient:
    """Small no-auth GET client locked to the configured first-party publisher host."""

    def __init__(
        self,
        *,
        client: httpx.Client | None = None,
        timeout_seconds: float = 15.0,
        maximum_payload_bytes: int = 5_000_000,
    ) -> None:
        if timeout_seconds <= 0 or maximum_payload_bytes < 1:
            raise ValueError("timeout and payload limit must be positive")
        self.timeout_seconds = timeout_seconds
        self.maximum_payload_bytes = maximum_payload_bytes
        self._owns_client = client is None
        self._client = client or httpx.Client(timeout=timeout_seconds, follow_redirects=False)

    def close(self) -> None:
        if self._owns_client:
            self._client.close()

    def __enter__(self) -> "OfficialWebClient":
        return self

    def __exit__(self, exc_type: object, exc: object, traceback: object) -> None:
        self.close()

    def fetch(self, descriptor: SourceDescriptor, url: str, *, retrieved_at: datetime) -> RawSourcePayload:
        if descriptor.authority is not SourceAuthority.OFFICIAL:
            raise ValueError("free official client requires OFFICIAL source authority")
        if retrieved_at.tzinfo is None:
            raise ValueError("retrieved_at must be timezone-aware")
        if not descriptor.permits(url):
            raise ValueError(f"URL is not permitted for source {descriptor.source_id}: {url}")
        try:
            response = self._client.get(
                url,
                headers={"Accept": "text/html,text/csv,application/json", "User-Agent": "forex-trader/free-official-macro"},
                timeout=self.timeout_seconds,
            )
        except httpx.HTTPError as exc:
            raise FreeOfficialSourceError(f"{descriptor.source_id} transport failure: {type(exc).__name__}") from exc
        if response.status_code != 200:
            raise FreeOfficialSourceError(f"{descriptor.source_id} returned HTTP {response.status_code}")
        final_url = str(response.url)
        if not descriptor.permits(final_url):
            raise FreeOfficialSourceError(f"{descriptor.source_id} response escaped approved publisher host")
        if len(response.content) > self.maximum_payload_bytes:
            raise FreeOfficialSourceError(f"{descriptor.source_id} payload exceeds configured maximum size")
        content_type = response.headers.get("content-type", "application/octet-stream").split(";", 1)[0]
        return RawSourcePayload.create(
            descriptor=descriptor,
            url=final_url,
            body=bytes(response.content),
            content_type=content_type,
            retrieved_at=retrieved_at.astimezone(UTC),
            published_at=retrieved_at.astimezone(UTC),
            available_at=retrieved_at.astimezone(UTC),
        )


def html_document(payload: RawSourcePayload) -> HtmlDocument:
    parser = _DocumentParser()
    try:
        parser.feed(payload.body.decode("utf-8", errors="replace"))
    except Exception as exc:
        raise FreeOfficialSourceError(f"failed to parse HTML from {payload.source_id}") from exc
    return HtmlDocument(
        text=" ".join(parser.text_parts),
        links=tuple(parser.links),
        rows=tuple(parser.rows),
    )


def fetch_usd(client: OfficialWebClient, *, retrieved_at: datetime) -> OfficialCurrencySnapshot:
    landing = client.fetch(FED, "https://www.federalreserve.gov/monetarypolicy.htm", retrieved_at=retrieved_at)
    landing_doc = html_document(landing)
    statement_urls: list[str] = []
    for href in landing_doc.links:
        absolute = urljoin(landing.url, href)
        if re.search(r"/newsevents/pressreleases/monetary\d{8}a\.htm$", absolute) and absolute not in statement_urls:
            statement_urls.append(absolute)
    statement_urls.sort(key=_date_digits_from_url, reverse=True)
    if not statement_urls:
        raise FreeOfficialSourceError("federal_reserve latest FOMC statement link was not found")
    statement_payloads = tuple(
        client.fetch(FED, url, retrieved_at=retrieved_at) for url in statement_urls[:2]
    )
    latest_rate = _fed_target_midpoint(html_document(statement_payloads[0]).text)
    previous_rate = (
        _fed_target_midpoint(html_document(statement_payloads[1]).text)
        if len(statement_payloads) > 1
        else None
    )
    policy_reference = _date_digits_from_url(statement_payloads[0].url)

    cpi = client.fetch(BLS, "https://www.bls.gov/news.release/cpi.t05.htm", retrieved_at=retrieved_at)
    cpi_rows = _month_year_rows(html_document(cpi).rows, value_selector=lambda cells: _last_decimal(cells))
    if len(cpi_rows) < 2:
        raise FreeOfficialSourceError("bls CPI table did not expose two monthly 12-month observations")
    latest_cpi, prior_cpi = cpi_rows[-1], cpi_rows[-2]
    return OfficialCurrencySnapshot(
        "USD",
        (landing, *statement_payloads, cpi),
        (
            OfficialIndicatorEvidence(
                "federal_reserve", "fed_funds_target_midpoint", "USD", "policy",
                latest_rate, previous_rate, True, policy_reference,
            ),
            OfficialIndicatorEvidence(
                "bls", "cpi_u_12m", "USD", "inflation",
                latest_cpi[1], prior_cpi[1], False, latest_cpi[0].isoformat(),
            ),
        ),
    )


def fetch_eur(client: OfficialWebClient, *, retrieved_at: datetime) -> OfficialCurrencySnapshot:
    policy = client.fetch(
        ECB_DATA_SOURCE,
        "https://data.ecb.europa.eu/key-figures/ecb-interest-rates-and-exchange-rates/key-ecb-interest-rates",
        retrieved_at=retrieved_at,
    )
    policy_doc = html_document(policy)
    match = re.search(
        r"Deposit facility\s+(\d{1,2}\s+[A-Za-z]+\s+\d{4})\s+(-?\d+(?:\.\d+)?)\s*%",
        policy_doc.text,
        flags=re.IGNORECASE,
    )
    if match is None:
        raise FreeOfficialSourceError("ecb deposit facility rate was not found")
    policy_rate = _decimal(match.group(2))
    policy_reference = _parse_date(match.group(1)).isoformat()

    hicp = client.fetch(
        ECB_DATA_SOURCE,
        "https://data-api.ecb.europa.eu/service/data/HICP/M.U2.N.000000.4D0.ANR?format=csvdata&lastNObservations=2&detail=dataonly",
        retrieved_at=retrieved_at,
    )
    inflation_rows = _csv_observations(hicp.body)
    if len(inflation_rows) < 2:
        raise FreeOfficialSourceError("ecb HICP API did not expose two observations")
    latest, prior = inflation_rows[-1], inflation_rows[-2]
    return OfficialCurrencySnapshot(
        "EUR",
        (policy, hicp),
        (
            OfficialIndicatorEvidence("ecb", "deposit_facility", "EUR", "policy", policy_rate, None, True, policy_reference),
            OfficialIndicatorEvidence("ecb", "hicp_total_annual", "EUR", "inflation", latest[1], prior[1], False, latest[0]),
        ),
    )


def fetch_gbp(client: OfficialWebClient, *, retrieved_at: datetime) -> OfficialCurrencySnapshot:
    rate = client.fetch(
        BOE,
        "https://www.bankofengland.co.uk/boeapps/database/Bank-Rate.asp",
        retrieved_at=retrieved_at,
    )
    rate_rows: list[tuple[date, Decimal]] = []
    for row in html_document(rate).rows:
        if len(row) < 2:
            continue
        try:
            when = datetime.strptime(row[0].strip(), "%d %b %y").date()
            value = _decimal(row[1])
        except (ValueError, InvalidOperation):
            continue
        rate_rows.append((when, value))
    rate_rows.sort(key=lambda item: item[0])
    if not rate_rows:
        raise FreeOfficialSourceError("bank_of_england Bank Rate history was not parsed")
    latest_rate = rate_rows[-1]
    prior_rate = rate_rows[-2][1] if len(rate_rows) > 1 else None

    cpi = client.fetch(
        OFFICE_NATIONAL_STATISTICS_SOURCE,
        "https://www.ons.gov.uk/economy/inflationandpriceindices/bulletins/consumerpriceinflation/latest",
        retrieved_at=retrieved_at,
    )
    text = html_document(cpi).text
    inflation = re.search(
        r"Consumer Prices Index \(CPI\) rose by\s+(-?\d+(?:\.\d+)?)%\s+in the 12 months to\s+([A-Za-z]+\s+\d{4}),\s+(?:down|up) from\s+(-?\d+(?:\.\d+)?)%\s+the previous month",
        text,
        flags=re.IGNORECASE,
    )
    if inflation is None:
        raise FreeOfficialSourceError("ons CPI annual-rate sentence was not found")
    return OfficialCurrencySnapshot(
        "GBP",
        (rate, cpi),
        (
            OfficialIndicatorEvidence("bank_of_england", "bank_rate", "GBP", "policy", latest_rate[1], prior_rate, True, latest_rate[0].isoformat()),
            OfficialIndicatorEvidence("office_national_statistics", "cpi_annual", "GBP", "inflation", _decimal(inflation.group(1)), _decimal(inflation.group(3)), False, inflation.group(2)),
        ),
    )


def fetch_cad(client: OfficialWebClient, *, retrieved_at: datetime) -> OfficialCurrencySnapshot:
    payload = client.fetch(
        BANK_OF_CANADA_SOURCE,
        "https://www.bankofcanada.ca/rates/indicators/key-variables/",
        retrieved_at=retrieved_at,
    )
    parsed: list[tuple[str, Decimal, Decimal]] = []
    for row in html_document(payload).rows:
        if len(row) < 6 or re.fullmatch(r"\d{4}-\d{2}", row[0].strip()) is None:
            continue
        try:
            inflation = _decimal(row[2])
            policy = _decimal(row[-2])
        except InvalidOperation:
            continue
        parsed.append((row[0].strip(), inflation, policy))
    parsed.sort(key=lambda item: item[0])
    if not parsed:
        raise FreeOfficialSourceError("bank_of_canada key variables table was not parsed")
    latest = parsed[-1]
    prior = parsed[-2] if len(parsed) > 1 else None
    return OfficialCurrencySnapshot(
        "CAD",
        (payload,),
        (
            OfficialIndicatorEvidence("bank_of_canada", "overnight_rate_target", "CAD", "policy", latest[2], None if prior is None else prior[2], True, latest[0]),
            OfficialIndicatorEvidence("bank_of_canada", "total_cpi_12m", "CAD", "inflation", latest[1], None if prior is None else prior[1], False, latest[0]),
        ),
    )


def fetch_aud(client: OfficialWebClient, *, retrieved_at: datetime) -> OfficialCurrencySnapshot:
    cash = client.fetch(
        RESERVE_BANK_AUSTRALIA_SOURCE,
        "https://www.rba.gov.au/statistics/cash-rate/",
        retrieved_at=retrieved_at,
    )
    cash_rows: list[tuple[date, Decimal]] = []
    for row in html_document(cash).rows:
        if len(row) < 3:
            continue
        try:
            when = _parse_date(row[0])
            target = _decimal(row[2])
        except (ValueError, InvalidOperation):
            continue
        cash_rows.append((when, target))
    cash_rows.sort(key=lambda item: item[0])
    if not cash_rows:
        raise FreeOfficialSourceError("rba cash-rate table was not parsed")

    cpi = client.fetch(
        RESERVE_BANK_AUSTRALIA_SOURCE,
        "https://www.rba.gov.au/inflation/measures-cpi.html",
        retrieved_at=retrieved_at,
    )
    cpi_rows = _year_context_month_rows(html_document(cpi).rows)
    if len(cpi_rows) < 2:
        raise FreeOfficialSourceError("rba monthly CPI table did not expose two observations")
    latest_cpi, prior_cpi = cpi_rows[-1], cpi_rows[-2]
    latest_rate = cash_rows[-1]
    prior_rate = cash_rows[-2][1] if len(cash_rows) > 1 else None
    return OfficialCurrencySnapshot(
        "AUD",
        (cash, cpi),
        (
            OfficialIndicatorEvidence("reserve_bank_australia", "cash_rate_target", "AUD", "policy", latest_rate[1], prior_rate, True, latest_rate[0].isoformat()),
            OfficialIndicatorEvidence("reserve_bank_australia", "cpi_monthly_year_ended", "AUD", "inflation", latest_cpi[1], prior_cpi[1], False, latest_cpi[0].isoformat()),
        ),
    )


def fetch_nzd(client: OfficialWebClient, *, retrieved_at: datetime) -> OfficialCurrencySnapshot:
    policy = client.fetch(
        RESERVE_BANK_NEW_ZEALAND_SOURCE,
        "https://www.rbnz.govt.nz/monetary-policy/about-monetary-policy/the-official-cash-rate",
        retrieved_at=retrieved_at,
    )
    policy_text = html_document(policy).text
    policy_match = re.search(
        r"Official Cash Rate\s+(-?\d+(?:\.\d+)?)\s*%\s+Updated:\s*[^,]*,\s*(\d{1,2}\s+[A-Za-z]+\s+\d{4})",
        policy_text,
        flags=re.IGNORECASE,
    )
    if policy_match is None:
        raise FreeOfficialSourceError("rbnz official cash rate was not found")

    cpi = client.fetch(
        RESERVE_BANK_NEW_ZEALAND_SOURCE,
        "https://www.rbnz.govt.nz/statistics/series/economic-indicators/prices",
        retrieved_at=retrieved_at,
    )
    rows: list[tuple[date, Decimal]] = []
    for row in html_document(cpi).rows:
        if len(row) < 4:
            continue
        try:
            when = datetime.strptime(row[0].strip(), "%b %Y").date()
        except ValueError:
            try:
                when = datetime.strptime(row[0].strip(), "%B %Y").date()
            except ValueError:
                continue
        try:
            value = _decimal(row[3])
        except InvalidOperation:
            continue
        rows.append((when, value))
    rows.sort(key=lambda item: item[0])
    if len(rows) < 2:
        raise FreeOfficialSourceError("rbnz CPI table did not expose two quarterly observations")
    latest, prior = rows[-1], rows[-2]
    return OfficialCurrencySnapshot(
        "NZD",
        (policy, cpi),
        (
            OfficialIndicatorEvidence("reserve_bank_new_zealand", "ocr", "NZD", "policy", _decimal(policy_match.group(1)), None, True, _parse_date(policy_match.group(2)).isoformat()),
            OfficialIndicatorEvidence("reserve_bank_new_zealand", "cpi_year_ended", "NZD", "inflation", latest[1], prior[1], False, latest[0].isoformat()),
        ),
    )


def fetch_chf(client: OfficialWebClient, *, retrieved_at: datetime) -> OfficialCurrencySnapshot:
    decisions = client.fetch(
        SWISS_NATIONAL_BANK_SOURCE,
        "https://www.snb.ch/en/the-snb/mandates-goals/monetary-policy/decisions",
        retrieved_at=retrieved_at,
    )
    doc = html_document(decisions)
    links = []
    for href in doc.links:
        absolute = urljoin(decisions.url, href)
        if re.search(r"/pre_\d{8}(?:$|[?#])", absolute) and absolute not in links:
            links.append(absolute.split("?", 1)[0].split("#", 1)[0])
    links.sort(key=_date_digits_from_url, reverse=True)
    if not links:
        raise FreeOfficialSourceError("snb latest monetary-policy assessment link was not found")
    release = client.fetch(SWISS_NATIONAL_BANK_SOURCE, links[0], retrieved_at=retrieved_at)
    text = html_document(release).text
    policy_match = re.search(
        r"SNB policy rate(?:\s+unchanged)?\s+at\s+(-?\d+(?:\.\d+)?)%",
        text,
        flags=re.IGNORECASE,
    )
    inflation_match = re.search(
        r"inflation has .*? from\s+(-?\d+(?:\.\d+)?)%\s+in\s+([A-Za-z]+)\s+to\s+(-?\d+(?:\.\d+)?)%\s+in\s+([A-Za-z]+)",
        text,
        flags=re.IGNORECASE,
    )
    if policy_match is None or inflation_match is None:
        raise FreeOfficialSourceError("snb policy/inflation assessment fields were not found")
    reference = _date_digits_from_url(release.url)
    return OfficialCurrencySnapshot(
        "CHF",
        (decisions, release),
        (
            OfficialIndicatorEvidence("swiss_national_bank", "policy_rate", "CHF", "policy", _decimal(policy_match.group(1)), None, True, reference),
            OfficialIndicatorEvidence("swiss_national_bank", "headline_inflation", "CHF", "inflation", _decimal(inflation_match.group(3)), _decimal(inflation_match.group(1)), False, f"{inflation_match.group(4)}:{reference[:4]}"),
        ),
    )


def fetch_jpy(client: OfficialWebClient, *, retrieved_at: datetime) -> OfficialCurrencySnapshot:
    year = retrieved_at.year
    index = client.fetch(
        BOJ,
        f"https://www.boj.or.jp/en/mopo/mpmdeci/state_{year}/index.htm",
        retrieved_at=retrieved_at,
    )
    decision_dates: list[date] = []
    for row in html_document(index).rows:
        if not row:
            continue
        try:
            parsed = _parse_date(row[0].replace("Apr.", "Apr").replace("Mar.", "Mar").replace("Jan.", "Jan"))
        except ValueError:
            continue
        decision_dates.append(parsed)
    if not decision_dates:
        raise FreeOfficialSourceError("bank_of_japan decision index did not expose a meeting date")
    latest_date = max(decision_dates)
    code = latest_date.strftime("%y%m%d")
    decision = client.fetch(
        BOJ,
        f"https://www.boj.or.jp/en/mopo/mpmdeci/state_{latest_date.year}/k{code}a.htm",
        retrieved_at=retrieved_at,
    )
    decision_text = html_document(decision).text
    policy_match = re.search(
        r"uncollateralized overnight call rate to remain at around\s+(-?\d+(?:\.\d+)?)\s+percent",
        decision_text,
        flags=re.IGNORECASE,
    )
    if policy_match is None:
        raise FreeOfficialSourceError("bank_of_japan policy interest rate was not found")

    stats = client.fetch(STATISTICS_JAPAN_SOURCE, "https://www.stat.go.jp/english/", retrieved_at=retrieved_at)
    stats_text = html_document(stats).text
    inflation_match = re.search(
        r"Consumer Price Index\s+(-?\d+(?:\.\d+)?)%\s+([A-Za-z]+)\s+(\d{4})\s+change over the year",
        stats_text,
        flags=re.IGNORECASE,
    )
    if inflation_match is None:
        raise FreeOfficialSourceError("statistics_japan latest CPI indicator was not found")
    return OfficialCurrencySnapshot(
        "JPY",
        (index, decision, stats),
        (
            OfficialIndicatorEvidence("bank_of_japan", "policy_interest_rate", "JPY", "policy", _decimal(policy_match.group(1)), None, True, latest_date.isoformat()),
            OfficialIndicatorEvidence("statistics_japan", "cpi_all_items_annual", "JPY", "inflation", _decimal(inflation_match.group(1)), None, False, f"{inflation_match.group(2)} {inflation_match.group(3)}"),
        ),
    )


FREE_OFFICIAL_CURRENCY_FETCHERS: dict[str, Callable[[OfficialWebClient], OfficialCurrencySnapshot]] = {}


def fetch_currency(
    currency: str,
    client: OfficialWebClient,
    *,
    retrieved_at: datetime,
) -> OfficialCurrencySnapshot:
    normalized = currency.upper()
    fetchers: dict[str, Callable[[OfficialWebClient, datetime], OfficialCurrencySnapshot]] = {
        "USD": lambda value, when: fetch_usd(value, retrieved_at=when),
        "EUR": lambda value, when: fetch_eur(value, retrieved_at=when),
        "GBP": lambda value, when: fetch_gbp(value, retrieved_at=when),
        "JPY": lambda value, when: fetch_jpy(value, retrieved_at=when),
        "CHF": lambda value, when: fetch_chf(value, retrieved_at=when),
        "CAD": lambda value, when: fetch_cad(value, retrieved_at=when),
        "AUD": lambda value, when: fetch_aud(value, retrieved_at=when),
        "NZD": lambda value, when: fetch_nzd(value, retrieved_at=when),
    }
    fetcher = fetchers.get(normalized)
    if fetcher is None:
        raise ValueError(f"unsupported free official currency: {currency}")
    return fetcher(client, retrieved_at)


def supported_currencies() -> tuple[str, ...]:
    return ("USD", "EUR", "GBP", "JPY", "CHF", "CAD", "AUD", "NZD")


def _decimal(value: str) -> Decimal:
    cleaned = value.strip().replace(",", "").replace("%", "")
    parsed = Decimal(cleaned)
    if not parsed.is_finite():
        raise InvalidOperation
    return parsed


def _last_decimal(cells: Iterable[str]) -> Decimal:
    for cell in reversed(tuple(cells)):
        try:
            return _decimal(cell)
        except (InvalidOperation, ValueError):
            continue
    raise InvalidOperation


def _parse_date(value: str) -> date:
    cleaned = " ".join(value.replace(",", " ").split())
    for fmt in ("%d %b %Y", "%d %B %Y", "%B %d %Y", "%b %d %Y", "%Y-%m-%d"):
        try:
            return datetime.strptime(cleaned, fmt).date()
        except ValueError:
            continue
    raise ValueError(f"unrecognized date: {value}")


def _date_digits_from_url(url: str) -> str:
    match = re.search(r"(20\d{6})", url)
    return match.group(1) if match else ""


def _fractional_decimal(value: str) -> Decimal:
    cleaned = value.strip()
    mixed = re.fullmatch(r"(\d+)-(\d+)/(\d+)", cleaned)
    if mixed:
        return Decimal(mixed.group(1)) + Decimal(mixed.group(2)) / Decimal(mixed.group(3))
    fraction = re.fullmatch(r"(\d+)/(\d+)", cleaned)
    if fraction:
        return Decimal(fraction.group(1)) / Decimal(fraction.group(2))
    return _decimal(cleaned)


def _fed_target_midpoint(text: str) -> Decimal:
    match = re.search(
        r"target range for the federal funds rate (?:at|of)\s+([0-9./-]+)\s+to\s+([0-9./-]+)\s+percent",
        text,
        flags=re.IGNORECASE,
    )
    if match is None:
        raise FreeOfficialSourceError("federal_reserve target range was not found")
    return (_fractional_decimal(match.group(1)) + _fractional_decimal(match.group(2))) / Decimal("2")


def _month_year_rows(
    rows: Iterable[tuple[str, ...]],
    *,
    value_selector: Callable[[tuple[str, ...]], Decimal],
) -> list[tuple[date, Decimal]]:
    result: list[tuple[date, Decimal]] = []
    for cells in rows:
        if not cells:
            continue
        parsed: date | None = None
        for fmt in ("%B %Y", "%b %Y"):
            try:
                parsed = datetime.strptime(cells[0].strip(), fmt).date()
                break
            except ValueError:
                continue
        if parsed is None:
            continue
        try:
            result.append((parsed, value_selector(cells)))
        except (InvalidOperation, ValueError):
            continue
    result.sort(key=lambda item: item[0])
    return result


def _year_context_month_rows(rows: Iterable[tuple[str, ...]]) -> list[tuple[date, Decimal]]:
    year: int | None = None
    result: list[tuple[date, Decimal]] = []
    for cells in rows:
        if not cells:
            continue
        first = cells[0].strip()
        if re.fullmatch(r"20\d{2}", first):
            year = int(first)
            continue
        if year is None or re.fullmatch(r"[A-Za-z]+", first) is None or len(cells) < 2:
            continue
        try:
            when = datetime.strptime(f"{first} {year}", "%B %Y").date()
            value = _decimal(cells[1])
        except (ValueError, InvalidOperation):
            continue
        result.append((when, value))
    result.sort(key=lambda item: item[0])
    return result


def _csv_observations(body: bytes) -> list[tuple[str, Decimal]]:
    text = body.decode("utf-8-sig", errors="strict")
    reader = csv.DictReader(io.StringIO(text))
    result: list[tuple[str, Decimal]] = []
    for row in reader:
        period = (row.get("TIME_PERIOD") or row.get("time_period") or "").strip()
        value = (row.get("OBS_VALUE") or row.get("obs_value") or "").strip()
        if not period or not value:
            continue
        try:
            result.append((period, _decimal(value)))
        except InvalidOperation:
            continue
    result.sort(key=lambda item: item[0])
    return result
