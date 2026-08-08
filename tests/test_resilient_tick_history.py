from __future__ import annotations

from datetime import UTC, datetime

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


def test_resilient_dukascopy_client_preserves_stricter_caller_values() -> None:
    client = ResilientDukascopyHistoryClient(
        timeout_seconds=60.0,
        max_concurrency=2,
        retries=14,
    )
    assert client.timeout_seconds == 60.0
    assert client.max_concurrency == 2
    assert client.retries == 14


def test_dukascopy_archive_urls_preserve_identical_hour_path() -> None:
    hour = datetime(2026, 7, 22, 22, tzinfo=UTC)
    urls = dukascopy_archive_urls("EUR_USD", hour)
    assert urls == (
        "https://datafeed.dukascopy.com/datafeed/EURUSD/2026/06/22/22h_ticks.bi5",
        "https://www.dukascopy.com/datafeed/EURUSD/2026/06/22/22h_ticks.bi5",
    )
