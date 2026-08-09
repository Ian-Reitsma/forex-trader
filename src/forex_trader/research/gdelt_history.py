from __future__ import annotations

import asyncio
import json
import re
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Iterable

import httpx

from forex_trader.research.public_history import GdeltDocHistoryClient, HistoricalNewsRecord

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
_INVALID_JSON_ESCAPE = re.compile(r'\\(?!["\\/bfnrtu])')


def parse_dirty_gdelt_json(raw: str) -> object:
    """Parse GDELT JSON while narrowly repairing invalid backslash escapes."""
    try:
        return json.loads(raw)
    except json.JSONDecodeError as first_error:
        repaired = _INVALID_JSON_ESCAPE.sub(r"\\\\", raw)
        if repaired == raw:
            raise ValueError("GDELT returned invalid JSON") from first_error
        try:
            return json.loads(repaired)
        except json.JSONDecodeError as second_error:
            raise ValueError("GDELT returned JSON that remains invalid after escape repair") from second_error


class ResilientGdeltDocHistoryClient(GdeltDocHistoryClient):
    """GDELT history client with sequential pacing, retry-after, and dirty JSON handling."""

    def __init__(
        self,
        *,
        cache_dir: str | Path = ".cache/forex-trader/gdelt",
        timeout_seconds: float = 45.0,
        retries: int = 6,
        max_concurrency: int = 1,
        min_request_interval_seconds: float = 1.0,
    ) -> None:
        super().__init__(cache_dir=cache_dir, timeout_seconds=timeout_seconds, retries=retries)
        if max_concurrency < 1:
            raise ValueError("max_concurrency must be positive")
        if min_request_interval_seconds < 0:
            raise ValueError("min_request_interval_seconds cannot be negative")
        self.max_concurrency = max_concurrency
        self.min_request_interval_seconds = min_request_interval_seconds
        self._semaphore = asyncio.Semaphore(max_concurrency)

    async def records(
        self,
        currencies: Iterable[str],
        start: datetime,
        end: datetime,
    ) -> tuple[HistoricalNewsRecord, ...]:
        if start.tzinfo is None or end.tzinfo is None:
            raise ValueError("GDELT range must be timezone-aware")
        if end <= start:
            raise ValueError("GDELT range end must be after start")
        normalized = tuple(sorted({currency.upper() for currency in currencies}))
        unsupported = [currency for currency in normalized if currency not in _GDELT_CURRENCY_QUERIES]
        if unsupported:
            raise ValueError(f"unsupported GDELT currencies: {', '.join(unsupported)}")

        timeout = httpx.Timeout(self.timeout_seconds)
        headers = {"User-Agent": "forex-trader-research/0.7.28"}
        records: list[HistoricalNewsRecord] = []
        async with httpx.AsyncClient(timeout=timeout, headers=headers, follow_redirects=True) as client:
            for currency in normalized:
                cursor = start.astimezone(UTC)
                final = end.astimezone(UTC)
                while cursor < final:
                    window_end = min(cursor + timedelta(days=1), final)
                    cache_file = self.cache_dir / currency / f"{cursor:%Y%m%d}.json"
                    was_cached = cache_file.exists()
                    records.extend(await self._window_records(client, currency, cursor, window_end))
                    cursor = window_end
                    if not was_cached and cursor < final and self.min_request_interval_seconds:
                        await asyncio.sleep(self.min_request_interval_seconds)

        unique: dict[tuple[str, str, datetime], HistoricalNewsRecord] = {}
        for record in records:
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
            payload = parse_dirty_gdelt_json(cache_file.read_text(encoding="utf-8"))
            return self._parse_articles(currency, payload, start, end)
        query = _GDELT_CURRENCY_QUERIES.get(currency)
        if query is None:
            raise ValueError(f"unsupported GDELT currency: {currency}")
        params = {
            "query": query,
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
                async with self._semaphore:
                    response = await client.get(_GDELT_DOC_URL, params=params)
                response.raise_for_status()
                break
            except httpx.HTTPStatusError as exc:
                if attempt + 1 >= self.retries:
                    raise
                if exc.response.status_code == 429:
                    retry_after_raw = exc.response.headers.get("Retry-After", "")
                    try:
                        retry_after = float(retry_after_raw)
                    except ValueError:
                        retry_after = 0.0
                    delay = max(retry_after, self.min_request_interval_seconds * (2**attempt), 1.0)
                else:
                    delay = 0.75 * (2**attempt)
                await asyncio.sleep(min(delay, 60.0))
            except (httpx.TimeoutException, httpx.NetworkError):
                if attempt + 1 >= self.retries:
                    raise
                await asyncio.sleep(min(0.75 * (2**attempt), 30.0))
        if response is None:
            return ()
        payload = parse_dirty_gdelt_json(response.text)
        if not isinstance(payload, dict):
            raise ValueError("GDELT DOC response must be a JSON object")
        cache_file.parent.mkdir(parents=True, exist_ok=True)
        cache_file.write_text(response.text, encoding="utf-8")
        return self._parse_articles(currency, payload, start, end)
