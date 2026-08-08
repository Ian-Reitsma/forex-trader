from __future__ import annotations

import asyncio
from datetime import datetime
from pathlib import Path

import httpx

from forex_trader.research.public_history import (
    DukascopyHistoryClient,
    HistoricalTick,
    decode_dukascopy_bi5,
    dukascopy_hour_url,
    dukascopy_symbol,
)


class ResilientDukascopyHistoryClient(DukascopyHistoryClient):
    """Dukascopy history client tuned for multi-week research campaigns.

    Historical hourly files occasionally return transient 5xx responses or drop
    connections. Preserve fail-closed source completeness, but reuse the HTTP
    connection pool, allow bounded parallel acquisition, and retry the entire
    transport-error family with capped exponential backoff before declaring the
    historical archive unavailable.
    """

    def __init__(
        self,
        *,
        cache_dir: str | Path = ".cache/forex-trader/dukascopy",
        timeout_seconds: float = 45.0,
        max_concurrency: int = 12,
        retries: int = 12,
    ) -> None:
        super().__init__(
            cache_dir=cache_dir,
            timeout_seconds=max(timeout_seconds, 45.0),
            max_concurrency=min(max_concurrency, 16),
            retries=max(retries, 12),
        )

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
            return decode_dukascopy_bi5(
                cache_file.read_bytes(),
                instrument=instrument,
                hour_start=hour_start,
            )

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
            except (httpx.TransportError, httpx.HTTPStatusError):
                response = None
                if attempt + 1 >= self.retries:
                    raise
                await asyncio.sleep(min(0.5 * (2**attempt), 8.0))

        if response is None or not response.content:
            return ()
        ticks = decode_dukascopy_bi5(
            response.content,
            instrument=instrument,
            hour_start=hour_start,
        )
        cache_file.parent.mkdir(parents=True, exist_ok=True)
        cache_file.write_bytes(response.content)
        return ticks
