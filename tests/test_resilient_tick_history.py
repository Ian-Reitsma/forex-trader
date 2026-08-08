from __future__ import annotations

from forex_trader.research.resilient_tick_history import ResilientDukascopyHistoryClient


def test_resilient_dukascopy_client_enforces_campaign_floor_and_ceiling() -> None:
    client = ResilientDukascopyHistoryClient(
        timeout_seconds=5.0,
        max_concurrency=20,
        retries=1,
    )
    assert client.timeout_seconds == 45.0
    assert client.max_concurrency == 4
    assert client.retries == 8


def test_resilient_dukascopy_client_preserves_stricter_caller_values() -> None:
    client = ResilientDukascopyHistoryClient(
        timeout_seconds=60.0,
        max_concurrency=2,
        retries=12,
    )
    assert client.timeout_seconds == 60.0
    assert client.max_concurrency == 2
    assert client.retries == 12
