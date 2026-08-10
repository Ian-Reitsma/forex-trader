from __future__ import annotations

import hashlib
import json
import os
import re
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from decimal import Decimal, InvalidOperation
from typing import Any
from urllib.parse import parse_qsl, quote, urlencode, urlparse, urlunparse

import httpx

from forex_trader.ingestion.official_sources import RawSourcePayload, SourceAuthority, SourceDescriptor


TRADING_ECONOMICS_SOURCE = SourceDescriptor(
    source_id="trading_economics",
    publisher="Trading Economics",
    authority=SourceAuthority.LICENSED,
    allowed_hosts=frozenset({"api.tradingeconomics.com"}),
)

_DEFAULT_COUNTRIES = (
    "United States",
    "Euro Area",
    "United Kingdom",
    "Japan",
    "Switzerland",
    "Canada",
    "Australia",
    "New Zealand",
    "China",
    "Czech Republic",
    "Denmark",
    "Hong Kong",
    "Hungary",
    "Mexico",
    "Norway",
    "Poland",
    "Singapore",
    "South Africa",
    "Sweden",
    "Turkey",
)

_COUNTRY_TO_CURRENCY = {
    "australia": "AUD",
    "canada": "CAD",
    "china": "CNH",
    "czech republic": "CZK",
    "czechia": "CZK",
    "denmark": "DKK",
    "euro area": "EUR",
    "euro zone": "EUR",
    "eurozone": "EUR",
    "hong kong": "HKD",
    "hungary": "HUF",
    "japan": "JPY",
    "mexico": "MXN",
    "new zealand": "NZD",
    "norway": "NOK",
    "poland": "PLN",
    "singapore": "SGD",
    "south africa": "ZAR",
    "sweden": "SEK",
    "switzerland": "CHF",
    "turkey": "TRY",
    "united kingdom": "GBP",
    "uk": "GBP",
    "united states": "USD",
    "united states of america": "USD",
    "usa": "USD",
}

_POLICY_TERMS = (
    "interest rate decision",
    "interest rate",
    "policy rate",
    "bank rate",
    "cash rate",
    "fed funds",
    "federal funds",
    "deposit facility rate",
    "refinancing rate",
    "monetary policy",
    "rate decision",
)
_INFLATION_TERMS = (
    "inflation",
    "consumer price",
    " cpi",
    "cpi ",
    "core cpi",
    "pce price",
    "core pce",
    "producer price",
    " ppi",
    "ppi ",
)
_LABOR_TERMS = (
    "unemployment",
    "employment",
    "non farm payroll",
    "nonfarm payroll",
    "jobless",
    "average earnings",
    "wage",
    "labour",
    "labor",
    "participation rate",
    "jolts",
    "adp employment",
)
_GROWTH_TERMS = (
    "gdp",
    "gross domestic product",
    "pmi",
    "retail sales",
    "industrial production",
    "manufacturing production",
    "business confidence",
    "consumer confidence",
    "trade balance",
    "current account",
    "factory orders",
    "durable goods",
    "construction output",
    "building permits",
    "housing starts",
    "new home sales",
    "existing home sales",
)
_NEGATIVE_HIGHER_TERMS = (
    "unemployment",
    "jobless",
    "claim",
    "layoff",
    "inflation",
    "consumer price",
    "cpi",
    "producer price",
    "ppi",
)


class TradingEconomicsApiError(RuntimeError):
    def __init__(self, message: str, *, status_code: int | None = None) -> None:
        super().__init__(message)
        self.status_code = status_code


class TradingEconomicsRateLimitedError(TradingEconomicsApiError):
    pass


@dataclass(frozen=True, slots=True)
class TradingEconomicsSettings:
    api_key: str | None = field(default=None, repr=False)
    base_url: str = "https://api.tradingeconomics.com"
    timeout_seconds: float = 15.0
    history_days: int = 30
    window_days: int = 7
    minimum_importance: int = 2
    auto_refresh: bool = True
    auth_mode: str = "header"
    maximum_payload_bytes: int = 8_000_000
    countries: tuple[str, ...] = _DEFAULT_COUNTRIES

    @classmethod
    def from_env(cls) -> "TradingEconomicsSettings":
        configured_countries = tuple(
            item.strip()
            for item in os.getenv("TRADING_ECONOMICS_COUNTRIES", ",".join(_DEFAULT_COUNTRIES)).split(",")
            if item.strip()
        )
        return cls(
            api_key=(os.getenv("TRADING_ECONOMICS_API_KEY") or "").strip() or None,
            base_url=os.getenv("TRADING_ECONOMICS_BASE_URL", "https://api.tradingeconomics.com").strip(),
            timeout_seconds=float(os.getenv("TRADING_ECONOMICS_TIMEOUT_SECONDS", "15")),
            history_days=int(os.getenv("TRADING_ECONOMICS_HISTORY_DAYS", "30")),
            window_days=int(os.getenv("TRADING_ECONOMICS_WINDOW_DAYS", "7")),
            minimum_importance=int(os.getenv("TRADING_ECONOMICS_MIN_IMPORTANCE", "2")),
            auto_refresh=_env_bool("TRADING_ECONOMICS_AUTO_REFRESH", True),
            auth_mode=os.getenv("TRADING_ECONOMICS_AUTH_MODE", "header").strip().lower(),
            maximum_payload_bytes=int(os.getenv("TRADING_ECONOMICS_MAX_PAYLOAD_BYTES", "8000000")),
            countries=configured_countries,
        )

    def validate(self, *, require_api_key: bool = True) -> None:
        parsed = urlparse(self.base_url)
        if parsed.scheme != "https" or parsed.hostname != "api.tradingeconomics.com":
            raise ValueError("Trading Economics base URL is locked to https://api.tradingeconomics.com")
        if require_api_key and not self.api_key:
            raise ValueError("TRADING_ECONOMICS_API_KEY is required")
        if self.timeout_seconds <= 0:
            raise ValueError("TRADING_ECONOMICS_TIMEOUT_SECONDS must be positive")
        if self.history_days < 1 or self.history_days > 90:
            raise ValueError("TRADING_ECONOMICS_HISTORY_DAYS must be in [1, 90]")
        if self.window_days < 1 or self.window_days > 31:
            raise ValueError("TRADING_ECONOMICS_WINDOW_DAYS must be in [1, 31]")
        if self.minimum_importance not in {1, 2, 3}:
            raise ValueError("TRADING_ECONOMICS_MIN_IMPORTANCE must be 1, 2, or 3")
        if self.auth_mode not in {"header", "query"}:
            raise ValueError("TRADING_ECONOMICS_AUTH_MODE must be header or query")
        if self.maximum_payload_bytes < 1:
            raise ValueError("TRADING_ECONOMICS_MAX_PAYLOAD_BYTES must be positive")
        if not self.countries:
            raise ValueError("TRADING_ECONOMICS_COUNTRIES cannot be empty")
        if any("/" in country or "?" in country or "#" in country for country in self.countries):
            raise ValueError("TRADING_ECONOMICS_COUNTRIES contains an invalid country name")


@dataclass(frozen=True, slots=True)
class TradingEconomicsCalendarEvent:
    event_id: str
    country: str
    currency: str
    indicator: str
    category: str
    scheduled_at: datetime
    actual: Decimal
    forecast: Decimal
    previous: Decimal
    importance: Decimal
    raw_importance: int
    higher_is_positive: bool
    vendor_source: str
    vendor_source_url: str

    @property
    def source_key(self) -> str:
        return f"trading_economics:{self.event_id}"


@dataclass(frozen=True, slots=True)
class TradingEconomicsCalendarSnapshot:
    payload: RawSourcePayload
    events: tuple[TradingEconomicsCalendarEvent, ...]
    rows_received: int
    skipped: dict[str, int]


class TradingEconomicsCalendarClient:
    """Read-only Trading Economics economic-calendar client.

    The preferred authentication mode is an Authorization header so the credential never
    enters the request URL. Query authentication exists only for vendor-plan compatibility;
    provenance URLs are sanitized before persistence either way.
    """

    def __init__(
        self,
        settings: TradingEconomicsSettings,
        *,
        client: httpx.Client | None = None,
    ) -> None:
        settings.validate()
        self.settings = settings
        self._owns_client = client is None
        self._client = client or httpx.Client(timeout=settings.timeout_seconds, follow_redirects=False)

    def close(self) -> None:
        if self._owns_client:
            self._client.close()

    def __enter__(self) -> "TradingEconomicsCalendarClient":
        return self

    def __exit__(self, exc_type: object, exc: object, traceback: object) -> None:
        self.close()

    def fetch_calendar(
        self,
        start: date,
        end: date,
        *,
        retrieved_at: datetime | None = None,
    ) -> TradingEconomicsCalendarSnapshot:
        if end < start:
            raise ValueError("Trading Economics calendar end date cannot precede start date")
        observed = (retrieved_at or datetime.now(UTC)).astimezone(UTC)
        countries = quote(",".join(self.settings.countries), safe=",")
        endpoint = (
            f"{self.settings.base_url.rstrip('/')}/calendar/country/{countries}/"
            f"{start.isoformat()}/{end.isoformat()}"
        )
        headers = {
            "Accept": "application/json",
            "User-Agent": "forex-trader/trading-economics-calendar",
        }
        params: dict[str, str] = {"values": "true", "f": "json"}
        assert self.settings.api_key is not None
        if self.settings.auth_mode == "header":
            headers["Authorization"] = self.settings.api_key
        else:
            params["c"] = self.settings.api_key
        try:
            response = self._client.get(
                endpoint,
                headers=headers,
                params=params,
                timeout=self.settings.timeout_seconds,
            )
        except httpx.HTTPError as exc:
            raise TradingEconomicsApiError(
                f"Trading Economics transport failure: {type(exc).__name__}"
            ) from exc
        if response.status_code in {409, 429}:
            raise TradingEconomicsRateLimitedError(
                f"Trading Economics rate limited the calendar request (HTTP {response.status_code})",
                status_code=response.status_code,
            )
        if response.status_code != 200:
            detail = _redact(response.text[:240], self.settings.api_key)
            raise TradingEconomicsApiError(
                f"Trading Economics HTTP {response.status_code}: {detail}",
                status_code=response.status_code,
            )
        final_url = _sanitize_url(str(response.url))
        if not TRADING_ECONOMICS_SOURCE.permits(final_url):
            raise TradingEconomicsApiError("Trading Economics response escaped the approved API host")
        if len(response.content) > self.settings.maximum_payload_bytes:
            raise TradingEconomicsApiError("Trading Economics calendar payload exceeds configured maximum size")
        try:
            decoded = response.json()
        except ValueError as exc:
            raise TradingEconomicsApiError("Trading Economics calendar response was not valid JSON") from exc
        if isinstance(decoded, dict) and isinstance(decoded.get("data"), list):
            rows = decoded["data"]
        elif isinstance(decoded, list):
            rows = decoded
        else:
            raise TradingEconomicsApiError("Trading Economics calendar response must be a JSON list")
        body = bytes(response.content)
        payload = RawSourcePayload.create(
            descriptor=TRADING_ECONOMICS_SOURCE,
            url=final_url,
            body=body,
            content_type=response.headers.get("content-type", "application/json").split(";", 1)[0],
            retrieved_at=observed,
            published_at=observed,
            available_at=observed,
        )
        events: list[TradingEconomicsCalendarEvent] = []
        skipped: dict[str, int] = {}
        for row in rows:
            if not isinstance(row, dict):
                _increment(skipped, "non_object")
                continue
            event, reason = parse_calendar_event(
                row,
                observed_at=observed,
                minimum_importance=self.settings.minimum_importance,
            )
            if event is None:
                _increment(skipped, reason or "invalid")
                continue
            events.append(event)
        events.sort(key=lambda item: (item.scheduled_at, item.currency, item.event_id))
        return TradingEconomicsCalendarSnapshot(payload, tuple(events), len(rows), skipped)


def parse_calendar_event(
    row: dict[str, Any],
    *,
    observed_at: datetime,
    minimum_importance: int = 2,
) -> tuple[TradingEconomicsCalendarEvent | None, str | None]:
    if observed_at.tzinfo is None:
        raise ValueError("observed_at must be timezone-aware")
    country = str(row.get("Country") or row.get("country") or "").strip()
    currency = _currency_for_row(row, country)
    if currency is None:
        return None, "unsupported_currency"
    indicator = str(
        row.get("Event")
        or row.get("event")
        or row.get("Category")
        or row.get("category")
        or ""
    ).strip()
    if not indicator:
        return None, "missing_indicator"
    category = _classify_indicator(indicator, str(row.get("Category") or ""))
    if category is None:
        return None, "unclassified_indicator"
    scheduled_raw = row.get("Date") or row.get("date") or row.get("ScheduledAt")
    try:
        scheduled_at = _parse_vendor_datetime(scheduled_raw)
    except ValueError:
        return None, "invalid_schedule"
    if scheduled_at > observed_at:
        return None, "not_released"
    raw_importance = _parse_importance(row.get("Importance") or row.get("importance"))
    if raw_importance < minimum_importance:
        return None, "low_importance"
    actual = _first_decimal(row, "ActualValue", "actual_value", "Actual", "actual")
    forecast = _first_decimal(row, "ForecastValue", "forecast_value", "Forecast", "forecast")
    previous = _first_decimal(row, "PreviousValue", "previous_value", "Previous", "previous")
    if actual is None:
        return None, "missing_actual"
    if forecast is None:
        return None, "missing_forecast"
    if previous is None:
        return None, "missing_previous"
    event_id = str(
        row.get("CalendarId")
        or row.get("CalendarID")
        or row.get("calendarId")
        or row.get("Id")
        or row.get("id")
        or ""
    ).strip()
    if not event_id:
        identity = json.dumps(
            {
                "country": country,
                "currency": currency,
                "indicator": indicator,
                "scheduled_at": scheduled_at.isoformat(),
            },
            sort_keys=True,
            separators=(",", ":"),
        )
        event_id = hashlib.sha256(identity.encode()).hexdigest()[:32]
    normalized_importance = {
        1: Decimal("0.50"),
        2: Decimal("0.75"),
        3: Decimal("1.00"),
    }[raw_importance]
    combined_label = f"{indicator} {row.get('Category') or ''}".lower()
    higher_is_positive = not any(term in combined_label for term in _NEGATIVE_HIGHER_TERMS)
    if category == "policy":
        higher_is_positive = True
    return (
        TradingEconomicsCalendarEvent(
            event_id=event_id,
            country=country,
            currency=currency,
            indicator=indicator,
            category=category,
            scheduled_at=scheduled_at,
            actual=actual,
            forecast=forecast,
            previous=previous,
            importance=normalized_importance,
            raw_importance=raw_importance,
            higher_is_positive=higher_is_positive,
            vendor_source=str(row.get("Source") or row.get("source") or "").strip(),
            vendor_source_url=str(
                row.get("SourceURL")
                or row.get("SourceUrl")
                or row.get("source_url")
                or ""
            ).strip(),
        ),
        None,
    )


def _currency_for_row(row: dict[str, Any], country: str) -> str | None:
    explicit = str(row.get("Currency") or row.get("currency") or "").strip().upper()
    if re.fullmatch(r"[A-Z]{3}", explicit):
        return "CNH" if explicit == "CNY" else explicit
    return _COUNTRY_TO_CURRENCY.get(" ".join(country.lower().split()))


def _classify_indicator(indicator: str, category: str) -> str | None:
    text = f" {indicator} {category} ".lower()
    if any(term in text for term in _POLICY_TERMS):
        return "policy"
    if any(term in text for term in _INFLATION_TERMS):
        return "inflation"
    if any(term in text for term in _LABOR_TERMS):
        return "labor"
    if any(term in text for term in _GROWTH_TERMS):
        return "growth"
    return None


def _parse_vendor_datetime(value: object) -> datetime:
    if value is None or not str(value).strip():
        raise ValueError("calendar event is missing Date")
    text = str(value).strip().replace("Z", "+00:00")
    parsed = datetime.fromisoformat(text)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def _parse_importance(value: object) -> int:
    try:
        parsed = int(Decimal(str(value or "1")))
    except (InvalidOperation, ValueError):
        return 1
    return max(1, min(3, parsed))


def _first_decimal(row: dict[str, Any], *keys: str) -> Decimal | None:
    for key in keys:
        if key not in row:
            continue
        parsed = _parse_decimal(row.get(key))
        if parsed is not None:
            return parsed
    return None


def _parse_decimal(value: object) -> Decimal | None:
    if value is None:
        return None
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float, Decimal)):
        try:
            result = Decimal(str(value))
        except InvalidOperation:
            return None
        return result if result.is_finite() else None
    text = str(value).strip()
    if not text or text.lower() in {"n/a", "na", "null", "none", "-"}:
        return None
    cleaned = text.replace("−", "-").replace(",", "").replace("%", "").strip()
    cleaned = re.sub(r"^[^0-9+\-.]+", "", cleaned)
    match = re.fullmatch(r"([+-]?(?:\d+(?:\.\d*)?|\.\d+))\s*([KMBT])?", cleaned, flags=re.IGNORECASE)
    if not match:
        return None
    try:
        result = Decimal(match.group(1))
    except InvalidOperation:
        return None
    suffix = (match.group(2) or "").upper()
    multiplier = {
        "": Decimal("1"),
        "K": Decimal("1000"),
        "M": Decimal("1000000"),
        "B": Decimal("1000000000"),
        "T": Decimal("1000000000000"),
    }[suffix]
    result *= multiplier
    return result if result.is_finite() else None


def _sanitize_url(url: str) -> str:
    parsed = urlparse(url)
    query = [(key, value) for key, value in parse_qsl(parsed.query, keep_blank_values=True) if key.lower() not in {"c", "client"}]
    return urlunparse(parsed._replace(query=urlencode(query)))


def _redact(value: str, secret: str | None) -> str:
    if not secret:
        return value
    return value.replace(secret, "[REDACTED]")


def _increment(counter: dict[str, int], key: str) -> None:
    counter[key] = counter.get(key, 0) + 1


def _env_bool(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}
