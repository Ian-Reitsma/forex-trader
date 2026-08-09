from __future__ import annotations

import asyncio
import json
import lzma
import struct
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Iterable
from uuid import NAMESPACE_URL, uuid5

import httpx

from forex_trader.domain.macro_history import MacroObservation
from forex_trader.domain.models import Candle

_DUKASCOPY_RECORD = struct.Struct(">3I2f")
_DUKASCOPY_BASE_URL = "https://datafeed.dukascopy.com/datafeed"
_GDELT_DOC_URL = "https://api.gdeltproject.org/api/v2/doc/doc"

_GDELT_CURRENCY_QUERIES: dict[str, str] = {
    "USD": '("Federal Reserve" OR "US inflation" OR "US jobs" OR "US economy" OR dollar)',
    "EUR": '("European Central Bank" OR ECB OR eurozone OR euro)',
    "GBP": '("Bank of England" OR BOE OR sterling OR "UK economy")',
    "JPY": '("Bank of Japan" OR BOJ OR yen OR "Japan economy")',
    "CHF": '("Swiss National Bank" OR SNB OR franc OR "Swiss economy")',
    "CAD": '("Bank of Canada" OR BOC OR "Canadian dollar" OR "Canada economy")',
    "AUD": '("Reserve Bank of Australia" OR RBA OR "Australian dollar" OR "Australia economy")',
    "NZD": '("Reserve Bank of New Zealand" OR RBNZ OR "New Zealand dollar" OR "New Zealand economy")',
}

_NEWS_RELEVANCE_TERMS = (
    "rate",
    "rates",
    "inflation",
    "cpi",
    "pce",
    "ppi",
    "jobs",
    "employment",
    "wages",
    "growth",
    "gdp",
    "economy",
    "recession",
    "hawkish",
    "dovish",
    "hike",
    "cut",
    "tightening",
    "easing",
    "central bank",
    "federal reserve",
    "ecb",
    "boe",
    "boj",
    "snb",
    "boc",
    "rba",
    "rbnz",
)


@dataclass(frozen=True, slots=True)
class HistoricalTick:
    instrument: str
    time: datetime
    bid: Decimal
    ask: Decimal
    bid_volume: Decimal = Decimal("0")
    ask_volume: Decimal = Decimal("0")

    def __post_init__(self) -> None:
        if self.time.tzinfo is None:
            raise ValueError("historical tick time must be timezone-aware")
        if self.bid <= 0 or self.ask <= 0:
            raise ValueError("historical tick prices must be positive")
        if self.ask < self.bid:
            raise ValueError("historical tick ask must be >= bid")
        if self.bid_volume < 0 or self.ask_volume < 0:
            raise ValueError("historical tick volumes cannot be negative")

    @property
    def mid(self) -> Decimal:
        return (self.bid + self.ask) / Decimal("2")

    @property
    def spread(self) -> Decimal:
        return self.ask - self.bid


@dataclass(frozen=True, slots=True)
class HistoricalNewsRecord:
    currency: str
    seen_at: datetime
    title: str
    url: str
    domain: str = ""

    def __post_init__(self) -> None:
        if self.seen_at.tzinfo is None:
            raise ValueError("historical news seen_at must be timezone-aware")
        if len(self.currency) != 3:
            raise ValueError("historical news currency must be a three-letter code")
        if not self.title.strip():
            raise ValueError("historical news title is required")


def dukascopy_symbol(instrument: str) -> str:
    normalized = instrument.upper().replace("/", "_")
    parts = normalized.split("_")
    if len(parts) != 2 or any(len(part) != 3 for part in parts):
        raise ValueError(f"unsupported FX instrument: {instrument}")
    return "".join(parts)


def dukascopy_price_divisor(instrument: str) -> Decimal:
    normalized = instrument.upper().replace("/", "_")
    quote_currency = normalized.split("_")[-1]
    return Decimal("1000") if quote_currency == "JPY" else Decimal("100000")


def dukascopy_hour_url(instrument: str, hour_start: datetime) -> str:
    if hour_start.tzinfo is None:
        raise ValueError("hour_start must be timezone-aware")
    utc_hour = hour_start.astimezone(UTC)
    symbol = dukascopy_symbol(instrument)
    zero_indexed_month = utc_hour.month - 1
    return (
        f"{_DUKASCOPY_BASE_URL}/{symbol}/{utc_hour.year:04d}/{zero_indexed_month:02d}/"
        f"{utc_hour.day:02d}/{utc_hour.hour:02d}h_ticks.bi5"
    )


def decode_dukascopy_bi5(payload: bytes, *, instrument: str, hour_start: datetime) -> tuple[HistoricalTick, ...]:
    if hour_start.tzinfo is None:
        raise ValueError("hour_start must be timezone-aware")
    if not payload:
        return ()
    try:
        raw = lzma.decompress(payload)
    except lzma.LZMAError as exc:
        raise ValueError("invalid Dukascopy BI5 LZMA payload") from exc
    if len(raw) % _DUKASCOPY_RECORD.size:
        raise ValueError("Dukascopy BI5 payload has a partial tick record")

    normalized = instrument.upper().replace("/", "_")
    divisor = dukascopy_price_divisor(normalized)
    base_hour = hour_start.astimezone(UTC).replace(minute=0, second=0, microsecond=0)
    ticks: list[HistoricalTick] = []
    previous_time: datetime | None = None
    for offset in range(0, len(raw), _DUKASCOPY_RECORD.size):
        milliseconds, ask_raw, bid_raw, ask_volume, bid_volume = _DUKASCOPY_RECORD.unpack_from(raw, offset)
        tick_time = base_hour + timedelta(milliseconds=milliseconds)
        if previous_time is not None and tick_time < previous_time:
            raise ValueError("Dukascopy BI5 ticks are not ordered within the hour")
        previous_time = tick_time
        ticks.append(
            HistoricalTick(
                instrument=normalized,
                time=tick_time,
                bid=Decimal(bid_raw) / divisor,
                ask=Decimal(ask_raw) / divisor,
                bid_volume=Decimal(str(bid_volume)),
                ask_volume=Decimal(str(ask_volume)),
            )
        )
    return tuple(ticks)


def _hour_starts(start: datetime, end: datetime) -> tuple[datetime, ...]:
    if start.tzinfo is None or end.tzinfo is None:
        raise ValueError("historical range must be timezone-aware")
    if end <= start:
        raise ValueError("historical range end must be after start")
    cursor = start.astimezone(UTC).replace(minute=0, second=0, microsecond=0)
    values: list[datetime] = []
    while cursor < end.astimezone(UTC):
        # FX is effectively closed for the majority of Saturday and Sunday. Avoid
        # thousands of known-empty requests while still retaining Sunday evening UTC.
        if cursor.weekday() != 5 and not (cursor.weekday() == 6 and cursor.hour < 20):
            values.append(cursor)
        cursor += timedelta(hours=1)
    return tuple(values)


class DukascopyHistoryClient:
    def __init__(
        self,
        *,
        cache_dir: str | Path = ".cache/forex-trader/dukascopy",
        timeout_seconds: float = 30.0,
        max_concurrency: int = 16,
        retries: int = 3,
    ) -> None:
        if max_concurrency < 1:
            raise ValueError("max_concurrency must be positive")
        if retries < 1:
            raise ValueError("retries must be positive")
        self.cache_dir = Path(cache_dir)
        self.timeout_seconds = timeout_seconds
        self.max_concurrency = max_concurrency
        self.retries = retries

    async def ticks(self, instrument: str, start: datetime, end: datetime) -> tuple[HistoricalTick, ...]:
        normalized = instrument.upper().replace("/", "_")
        hours = _hour_starts(start, end)
        semaphore = asyncio.Semaphore(self.max_concurrency)
        timeout = httpx.Timeout(self.timeout_seconds)
        headers = {"User-Agent": "forex-trader-research/0.7.28"}
        async with httpx.AsyncClient(timeout=timeout, headers=headers, follow_redirects=True) as client:
            chunks = await asyncio.gather(
                *(self._load_hour(client, semaphore, normalized, hour) for hour in hours)
            )
        lower_bound = start.astimezone(UTC)
        upper_bound = end.astimezone(UTC)
        merged = [tick for chunk in chunks for tick in chunk if lower_bound <= tick.time < upper_bound]
        merged.sort(key=lambda item: item.time)
        return tuple(merged)

    async def _load_hour(
        self,
        client: httpx.AsyncClient,
        semaphore: asyncio.Semaphore,
        instrument: str,
        hour_start: datetime,
    ) -> tuple[HistoricalTick, ...]:
        symbol = dukascopy_symbol(instrument)
        cache_file = (
            self.cache_dir
            / symbol
            / f"{hour_start.year:04d}"
            / f"{hour_start.month:02d}"
            / f"{hour_start.day:02d}"
            / f"{hour_start.hour:02d}h_ticks.bi5"
        )
        if cache_file.exists():
            return decode_dukascopy_bi5(cache_file.read_bytes(), instrument=instrument, hour_start=hour_start)

        url = dukascopy_hour_url(instrument, hour_start)
        response: httpx.Response | None = None
        for attempt in range(self.retries):
            try:
                async with semaphore:
                    response = await client.get(url)
                if response.status_code in {204, 404}:
                    return ()
                response.raise_for_status()
                break
            except (httpx.TimeoutException, httpx.NetworkError, httpx.HTTPStatusError):
                if attempt + 1 >= self.retries:
                    raise
                await asyncio.sleep(0.35 * (2**attempt))
        if response is None or not response.content:
            return ()
        ticks = decode_dukascopy_bi5(response.content, instrument=instrument, hour_start=hour_start)
        cache_file.parent.mkdir(parents=True, exist_ok=True)
        cache_file.write_bytes(response.content)
        return ticks


def resample_midpoint_candles(
    ticks: Iterable[HistoricalTick],
    *,
    timeframe: timedelta,
) -> tuple[Candle, ...]:
    seconds = int(timeframe.total_seconds())
    if seconds < 1:
        raise ValueError("timeframe must be positive")
    ordered = sorted(ticks, key=lambda item: item.time)
    if not ordered:
        return ()

    buckets: dict[int, list[HistoricalTick]] = {}
    for tick in ordered:
        epoch = int(tick.time.astimezone(UTC).timestamp())
        bucket = epoch - (epoch % seconds)
        buckets.setdefault(bucket, []).append(tick)

    candles: list[Candle] = []
    for bucket, values in sorted(buckets.items()):
        mids = [item.mid for item in values]
        candles.append(
            Candle(
                time=datetime.fromtimestamp(bucket, tz=UTC),
                open=mids[0],
                high=max(mids),
                low=min(mids),
                close=mids[-1],
                volume=len(values),
                complete=True,
            )
        )
    return tuple(candles)


def _parse_gdelt_datetime(value: str) -> datetime:
    cleaned = value.strip()
    formats = (
        "%Y%m%dT%H%M%SZ",
        "%Y%m%d%H%M%S",
        "%Y-%m-%dT%H:%M:%SZ",
        "%Y-%m-%d %H:%M:%S",
    )
    for fmt in formats:
        try:
            return datetime.strptime(cleaned, fmt).replace(tzinfo=UTC)
        except ValueError:
            continue
    try:
        parsed = datetime.fromisoformat(cleaned.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError(f"unsupported GDELT timestamp: {value}") from exc
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def _date_windows(start: datetime, end: datetime) -> tuple[tuple[datetime, datetime], ...]:
    if start.tzinfo is None or end.tzinfo is None:
        raise ValueError("GDELT range must be timezone-aware")
    if end <= start:
        raise ValueError("GDELT range end must be after start")
    cursor = start.astimezone(UTC)
    windows: list[tuple[datetime, datetime]] = []
    while cursor < end.astimezone(UTC):
        next_midnight = datetime.combine(cursor.date() + timedelta(days=1), time.min, tzinfo=UTC)
        window_end = min(next_midnight, end.astimezone(UTC))
        windows.append((cursor, window_end))
        cursor = window_end
    return tuple(windows)


class GdeltDocHistoryClient:
    """Download timestamped headline history from the open GDELT DOC 2.0 API.

    GDELT DOC is used as a public research news overlay, not as a substitute for
    licensed point-in-time economic consensus or an official central-bank archive.
    """

    def __init__(
        self,
        *,
        cache_dir: str | Path = ".cache/forex-trader/gdelt",
        timeout_seconds: float = 45.0,
        retries: int = 3,
    ) -> None:
        self.cache_dir = Path(cache_dir)
        self.timeout_seconds = timeout_seconds
        self.retries = retries

    async def records(
        self,
        currencies: Iterable[str],
        start: datetime,
        end: datetime,
    ) -> tuple[HistoricalNewsRecord, ...]:
        normalized = tuple(sorted({currency.upper() for currency in currencies}))
        unsupported = [currency for currency in normalized if currency not in _GDELT_CURRENCY_QUERIES]
        if unsupported:
            raise ValueError(f"unsupported GDELT currencies: {', '.join(unsupported)}")
        timeout = httpx.Timeout(self.timeout_seconds)
        headers = {"User-Agent": "forex-trader-research/0.7.28"}
        async with httpx.AsyncClient(timeout=timeout, headers=headers, follow_redirects=True) as client:
            chunks = await asyncio.gather(
                *(
                    self._window_records(client, currency, window_start, window_end)
                    for currency in normalized
                    for window_start, window_end in _date_windows(start, end)
                )
            )
        unique: dict[tuple[str, str, datetime], HistoricalNewsRecord] = {}
        for chunk in chunks:
            for record in chunk:
                unique[(record.currency, record.url or record.title, record.seen_at)] = record
        return tuple(sorted(unique.values(), key=lambda item: (item.seen_at, item.currency, item.url, item.title)))

    async def _window_records(
        self,
        client: httpx.AsyncClient,
        currency: str,
        start: datetime,
        end: datetime,
    ) -> tuple[HistoricalNewsRecord, ...]:
        cache_file = self.cache_dir / currency / f"{start:%Y%m%d}.json"
        if cache_file.exists():
            payload = json.loads(cache_file.read_text(encoding="utf-8"))
            return self._parse_articles(currency, payload, start, end)

        params = {
            "query": _GDELT_CURRENCY_QUERIES[currency],
            "mode": "artlist",
            "format": "json",
            "maxrecords": "250",
            "sort": "datedesc",
            "startdatetime": start.astimezone(UTC).strftime("%Y%m%d%H%M%S"),
            "enddatetime": end.astimezone(UTC).strftime("%Y%m%d%H%M%S"),
        }
        response: httpx.Response | None = None
        for attempt in range(self.retries):
            try:
                response = await client.get(_GDELT_DOC_URL, params=params)
                response.raise_for_status()
                break
            except (httpx.TimeoutException, httpx.NetworkError, httpx.HTTPStatusError):
                if attempt + 1 >= self.retries:
                    raise
                await asyncio.sleep(0.5 * (2**attempt))
        if response is None:
            return ()
        payload = response.json()
        cache_file.parent.mkdir(parents=True, exist_ok=True)
        cache_file.write_text(json.dumps(payload, sort_keys=True), encoding="utf-8")
        return self._parse_articles(currency, payload, start, end)

    @staticmethod
    def _parse_articles(
        currency: str,
        payload: object,
        start: datetime,
        end: datetime,
    ) -> tuple[HistoricalNewsRecord, ...]:
        if not isinstance(payload, dict):
            raise ValueError("GDELT DOC response must be an object")
        articles = payload.get("articles", [])
        if not isinstance(articles, list):
            raise ValueError("GDELT DOC articles must be a list")
        values: list[HistoricalNewsRecord] = []
        for raw in articles:
            if not isinstance(raw, dict):
                continue
            title = str(raw.get("title") or "").strip()
            if not title:
                continue
            lowered = title.lower()
            if not any(term in lowered for term in _NEWS_RELEVANCE_TERMS):
                continue
            seen_raw = str(raw.get("seendate") or raw.get("seenDate") or "").strip()
            if not seen_raw:
                continue
            seen_at = _parse_gdelt_datetime(seen_raw)
            if seen_at < start.astimezone(UTC) or seen_at >= end.astimezone(UTC):
                continue
            values.append(
                HistoricalNewsRecord(
                    currency=currency,
                    seen_at=seen_at,
                    title=title,
                    url=str(raw.get("url") or "").strip(),
                    domain=str(raw.get("domain") or "").strip(),
                )
            )
        return tuple(values)


def gdelt_news_observations(
    records: Iterable[HistoricalNewsRecord],
    *,
    source_weight: Decimal = Decimal("0.55"),
) -> tuple[MacroObservation, ...]:
    if not Decimal("0") <= source_weight <= Decimal("1"):
        raise ValueError("source_weight must be in [0,1]")
    observations: list[MacroObservation] = []
    for record in records:
        identity = f"gdelt-doc:{record.currency}:{record.seen_at.isoformat()}:{record.url}:{record.title}"
        observations.append(
            MacroObservation.news(
                currency=record.currency,
                headline=record.title,
                available_at=record.seen_at,
                source="gdelt-doc-2.0",
                source_weight=source_weight,
                observation_id=uuid5(NAMESPACE_URL, identity),
            )
        )
    return tuple(sorted(observations, key=lambda item: (item.available_at, str(item.observation_id))))


def currencies_for_instruments(instruments: Iterable[str]) -> tuple[str, ...]:
    currencies: set[str] = set()
    for instrument in instruments:
        normalized = instrument.upper().replace("/", "_")
        parts = normalized.split("_")
        if len(parts) != 2 or any(len(part) != 3 for part in parts):
            raise ValueError(f"unsupported FX instrument: {instrument}")
        currencies.update(parts)
    return tuple(sorted(currencies))


def utc_range(start_date: date, end_date: date) -> tuple[datetime, datetime]:
    if end_date <= start_date:
        raise ValueError("end_date must be after start_date")
    return (
        datetime.combine(start_date, time.min, tzinfo=UTC),
        datetime.combine(end_date, time.min, tzinfo=UTC),
    )
