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


_DUKASCOPY_ARCHIVE_HOSTS = (
    "https://datafeed.dukascopy.com/datafeed/",
    "https://www.dukascopy.com/datafeed/",
)


def dukascopy_archive_urls(instrument: str, hour_start: datetime) -> tuple[str, ...]:
    """Return equivalent first-party Dukascopy BI5 archive locations for one hour."""
    primary = dukascopy_hour_url(instrument, hour_start)
    marker = "/datafeed/"
    if marker not in primary:
        return (primary,)
    relative = primary.split(marker, maxsplit=1)[1]
    return tuple(f"{host}{relative}" for host in _DUKASCOPY_ARCHIVE_HOSTS)


class ResilientDukascopyHistoryClient(DukascopyHistoryClient):
    """Dukascopy history client tuned for multi-week research campaigns.

    Historical hourly files occasionally return transient 5xx responses or drop
    connections. Preserve fail-closed source completeness, but reuse the HTTP
    connection pool, allow bounded parallel acquisition, retry transport failures,
    and repeat the bulk sweep so successful hourly downloads are reused from disk
    while only remaining source holes are retried. A 204/404 from either first-party
    archive host is treated the same way as the base Dukascopy client: that market
    hour has no BI5 archive. Cached bytes must still decode as the requested BI5 hour.
    """

    def __init__(
        self,
        *,
        cache_dir: str | Path = ".cache/forex-trader/dukascopy",
        timeout_seconds: float = 45.0,
        max_concurrency: int = 12,
        retries: int = 12,
        recovery_sweeps: int = 4,
    ) -> None:
        if recovery_sweeps < 1:
            raise ValueError("recovery_sweeps must be positive")
        super().__init__(
            cache_dir=cache_dir,
            timeout_seconds=max(timeout_seconds, 45.0),
            max_concurrency=min(max_concurrency, 16),
            retries=max(retries, 12),
        )
        self.recovery_sweeps = recovery_sweeps

    async def ticks(
        self,
        instrument: str,
        start: datetime,
        end: datetime,
    ) -> tuple[HistoricalTick, ...]:
        """Complete the requested range or fail after repeated cache-aware sweeps."""
        last_error: Exception | None = None
        for sweep in range(self.recovery_sweeps):
            try:
                return await super().ticks(instrument, start, end)
            except (httpx.TransportError, httpx.HTTPStatusError) as exc:
                last_error = exc
                if sweep + 1 >= self.recovery_sweeps:
                    raise
                # Successful hourly files from the failed sweep are already cached,
                # so the next pass concentrates requests on the remaining holes.
                await asyncio.sleep(min(1.0 * (2**sweep), 8.0))
        if last_error is not None:
            raise last_error
        raise RuntimeError("historical range recovery exited unexpectedly")

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

        urls = dukascopy_archive_urls(instrument, hour_start)
        response: httpx.Response | None = None
        last_error: Exception | None = None
        attempts_per_host = max(2, self.retries // len(urls))
        for url in urls:
            for attempt in range(attempts_per_host):
                try:
                    async with semaphore:
                        response = await client.get(url)
                    if response.status_code in {204, 404}:
                        # One authoritative first-party archive host confirming that
                        # the hour is absent is sufficient. Do not let an earlier
                        # transient 5xx from the sibling host survive as stale state.
                        return ()
                    response.raise_for_status()
                    last_error = None
                    break
                except (httpx.TransportError, httpx.HTTPStatusError) as exc:
                    response = None
                    last_error = exc
                    if attempt + 1 < attempts_per_host:
                        await asyncio.sleep(min(0.5 * (2**attempt), 8.0))
            if response is not None and response.is_success:
                break

        if response is None or not response.is_success:
            if last_error is not None:
                raise last_error
            return ()
        if not response.content:
            return ()
        ticks = decode_dukascopy_bi5(
            response.content,
            instrument=instrument,
            hour_start=hour_start,
        )
        cache_file.parent.mkdir(parents=True, exist_ok=True)
        cache_file.write_bytes(response.content)
        return ticks
