from __future__ import annotations

import asyncio
from datetime import UTC, datetime

import httpx

import forex_trader.research.resilient_tick_history as resilient_module
from forex_trader.research.public_history import DukascopyHistoryClient
from forex_trader.research.resilient_tick_history import (
    ResilientDukascopyHistoryClient,
    dukascopy_archive_urls,
)


def test_resilient_dukascopy_client_enforces_campaign_floor_and_ceiling() -> None:
    client = ResilientDukascopyHistoryClient(
        timeout_seconds=5.0,
        max_concurrency=20,
        retries=1,
    )
    assert client.timeout_seconds == 45.0
    assert client.max_concurrency == 16
    assert client.retries == 12
    assert client.recovery_sweeps == 4


def test_resilient_dukascopy_client_preserves_stricter_caller_values() -> None:
    client = ResilientDukascopyHistoryClient(
        timeout_seconds=60.0,
        max_concurrency=2,
        retries=14,
        recovery_sweeps=6,
    )
    assert client.timeout_seconds == 60.0
    assert client.max_concurrency == 2
    assert client.retries == 14
    assert client.recovery_sweeps == 6


def test_dukascopy_archive_urls_preserve_identical_hour_path() -> None:
    hour = datetime(2026, 7, 22, 22, tzinfo=UTC)
    urls = dukascopy_archive_urls("EUR_USD", hour)
    assert urls == (
        "https://datafeed.dukascopy.com/datafeed/EURUSD/2026/06/22/22h_ticks.bi5",
        "https://www.dukascopy.com/datafeed/EURUSD/2026/06/22/22h_ticks.bi5",
    )


def test_fallback_404_clears_stale_primary_503(tmp_path) -> None:  # type: ignore[no-untyped-def]
    hour = datetime(2026, 7, 24, 21, tzinfo=UTC)
    calls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        calls.append(url)
        if "datafeed.dukascopy.com" in url:
            return httpx.Response(503, request=request)
        return httpx.Response(404, request=request)

    async def exercise() -> tuple[object, ...]:
        history = ResilientDukascopyHistoryClient(
            cache_dir=tmp_path,
            max_concurrency=1,
            retries=4,
        )
        transport = httpx.MockTransport(handler)
        async with httpx.AsyncClient(transport=transport) as client:
            return await history._load_hour(client, asyncio.Semaphore(1), "EUR_USD", hour)

    assert asyncio.run(exercise()) == ()
    assert any("datafeed.dukascopy.com" in url for url in calls)
    assert any("www.dukascopy.com" in url for url in calls)


def test_bulk_range_recovery_retries_after_transport_failure(monkeypatch, tmp_path) -> None:  # type: ignore[no-untyped-def]
    attempts = 0

    async def fake_ticks(self, instrument, start, end):  # type: ignore[no-untyped-def]
        nonlocal attempts
        attempts += 1
        if attempts < 3:
            request = httpx.Request("GET", "https://datafeed.dukascopy.com/datafeed/test")
            raise httpx.ReadError("transient disconnect", request=request)
        return ()

    async def no_sleep(delay):  # type: ignore[no-untyped-def]
        return None

    monkeypatch.setattr(DukascopyHistoryClient, "ticks", fake_ticks)
    monkeypatch.setattr(resilient_module.asyncio, "sleep", no_sleep)
    history = ResilientDukascopyHistoryClient(cache_dir=tmp_path, recovery_sweeps=4)
    start = datetime(2026, 8, 3, 9, tzinfo=UTC)
    end = datetime(2026, 8, 3, 10, tzinfo=UTC)
    assert asyncio.run(history.ticks("EUR_USD", start, end)) == ()
    assert attempts == 3
