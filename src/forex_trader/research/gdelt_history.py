from __future__ import annotations

import asyncio
import json
import re
from datetime import datetime
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
    """Parse GDELT JSON while narrowly repairing invalid backslash escapes.

    Some DOC 2.0 ArticleList payloads contain publisher text with a bare backslash
    before a character that JSON does not define as an escape. We first attempt
    strict JSON. On that specific syntax family, only those invalid backslashes are
    escaped and the result is parsed again. We do not eval data, remove fields, or
    coerce an otherwise non-JSON response into an object.
    """
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
    """GDELT DOC client with bounded request concurrency and dirty-JSON handling."""

    def __init__(
        self,
        *,
        cache_dir: str | Path = ".cache/forex-trader/gdelt",
        timeout_seconds: float = 45.0,
        retries: int = 3,
        max_concurrency: int = 4,
    ) -> None:
        super().__init__(cache_dir=cache_dir, timeout_seconds=timeout_seconds, retries=retries)
        if max_concurrency < 1:
            raise ValueError("max_concurrency must be positive")
        self.max_concurrency = max_concurrency
        self._semaphore = asyncio.Semaphore(max_concurrency)

    async def records(
        self,
        currencies: Iterable[str],
        start: datetime,
        end: datetime,
    ) -> tuple[HistoricalNewsRecord, ...]:
        # Preserve the parent's validated currency/date-window and article filtering
        # while routing actual HTTP parsing through the hardened override below.
        return await super().records(currencies, start, end)

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
            "startdatetime": start.strftime("%Y%m%d%H%M%S"),
            "enddatetime": end.strftime("%Y%m%d%H%M%S"),
        }
        response: httpx.Response | None = None
        for attempt in range(self.retries):
            try:
                async with self._semaphore:
                    response = await client.get(_GDELT_DOC_URL, params=params)
                response.raise_for_status()
                break
            except (httpx.TimeoutException, httpx.NetworkError, httpx.HTTPStatusError):
                if attempt + 1 >= self.retries:
                    raise
                await asyncio.sleep(0.75 * (2**attempt))
        if response is None:
            return ()
        payload = parse_dirty_gdelt_json(response.text)
        if not isinstance(payload, dict):
            raise ValueError("GDELT DOC response must be a JSON object")
        cache_file.parent.mkdir(parents=True, exist_ok=True)
        cache_file.write_text(response.text, encoding="utf-8")
        return self._parse_articles(currency, payload, start, end)
