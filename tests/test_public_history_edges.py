from __future__ import annotations

import asyncio
import json
import lzma
import struct
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

import pytest

from forex_trader.research.gdelt_history import ResilientGdeltDocHistoryClient
from forex_trader.research.public_history import (
    DukascopyHistoryClient,
    GdeltDocHistoryClient,
    HistoricalNewsRecord,
    HistoricalTick,
    _date_windows,
    _hour_starts,
    currencies_for_instruments,
    decode_dukascopy_bi5,
    dukascopy_hour_url,
    dukascopy_symbol,
    resample_midpoint_candles,
    utc_range,
)


def _bi5(*rows: tuple[int, int, int, float, float]) -> bytes:
    return lzma.compress(b"".join(struct.pack(">3I2f", *row) for row in rows))


def test_historical_value_objects_reject_bad_inputs() -> None:
    now = datetime(2026, 7, 1, tzinfo=UTC)
    with pytest.raises(ValueError, match="timezone-aware"):
        HistoricalTick("EUR_USD", now.replace(tzinfo=None), Decimal("1"), Decimal("1.1"))
    with pytest.raises(ValueError, match="positive"):
        HistoricalTick("EUR_USD", now, Decimal("0"), Decimal("1"))
    with pytest.raises(ValueError, match="ask"):
        HistoricalTick("EUR_USD", now, Decimal("1.2"), Decimal("1.1"))
    with pytest.raises(ValueError, match="volumes"):
        HistoricalTick("EUR_USD", now, Decimal("1"), Decimal("1.1"), Decimal("-1"), Decimal("0"))
    with pytest.raises(ValueError, match="timezone-aware"):
        HistoricalNewsRecord("USD", now.replace(tzinfo=None), "rates", "https://example.com")
    with pytest.raises(ValueError, match="three-letter"):
        HistoricalNewsRecord("US", now, "rates", "https://example.com")
    with pytest.raises(ValueError, match="title"):
        HistoricalNewsRecord("USD", now, " ", "https://example.com")


def test_symbol_and_range_validation() -> None:
    now = datetime(2026, 7, 1, tzinfo=UTC)
    assert dukascopy_symbol("eur/usd") == "EURUSD"
    with pytest.raises(ValueError, match="unsupported"):
        dukascopy_symbol("EURUSD")
    with pytest.raises(ValueError, match="timezone-aware"):
        dukascopy_hour_url("EUR_USD", now.replace(tzinfo=None))
    with pytest.raises(ValueError, match="timezone-aware"):
        _hour_starts(now.replace(tzinfo=None), now + timedelta(hours=1))
    with pytest.raises(ValueError, match="after start"):
        _hour_starts(now, now)
    with pytest.raises(ValueError, match="after start"):
        _date_windows(now, now)
    with pytest.raises(ValueError, match="after start"):
        utc_range(date(2026, 7, 2), date(2026, 7, 1))
    with pytest.raises(ValueError, match="unsupported"):
        currencies_for_instruments(("EURUSD",))
    assert currencies_for_instruments(("EUR_USD", "GBP_USD")) == ("EUR", "GBP", "USD")


def test_hour_starts_skips_closed_weekend_and_date_windows_split_days() -> None:
    friday = datetime(2026, 7, 3, 23, tzinfo=UTC)
    monday = datetime(2026, 7, 6, 2, tzinfo=UTC)
    hours = _hour_starts(friday, monday)
    assert friday in hours
    assert all(item.weekday() != 5 for item in hours)
    assert all(not (item.weekday() == 6 and item.hour < 20) for item in hours)
    windows = _date_windows(friday + timedelta(minutes=30), friday + timedelta(days=2, hours=2))
    assert windows[0][0].minute == 30
    assert windows[-1][1] == friday + timedelta(days=2, hours=2)


def test_decode_rejects_partial_and_out_of_order_records() -> None:
    hour = datetime(2026, 7, 1, 10, tzinfo=UTC)
    partial = lzma.compress(struct.pack(">3I2f", 100, 110010, 110000, 1.0, 1.0) + b"x")
    with pytest.raises(ValueError, match="partial"):
        decode_dukascopy_bi5(partial, instrument="EUR_USD", hour_start=hour)
    with pytest.raises(ValueError, match="not ordered"):
        decode_dukascopy_bi5(
            _bi5((500, 110010, 110000, 1.0, 1.0), (100, 110011, 110001, 1.0, 1.0)),
            instrument="EUR_USD",
            hour_start=hour,
        )
    assert decode_dukascopy_bi5(b"", instrument="EUR_USD", hour_start=hour) == ()


def test_dukascopy_client_reads_cached_hour_without_network(tmp_path) -> None:  # type: ignore[no-untyped-def]
    hour = datetime(2026, 7, 1, 10, tzinfo=UTC)
    cache = tmp_path / "EURUSD" / "2026" / "07" / "01" / "10h_ticks.bi5"
    cache.parent.mkdir(parents=True)
    cache.write_bytes(_bi5((100, 110010, 110000, 1.0, 1.0), (200, 110020, 110010, 1.0, 1.0)))
    client = DukascopyHistoryClient(cache_dir=tmp_path, max_concurrency=1)
    ticks = asyncio.run(client.ticks("EUR_USD", hour, hour + timedelta(hours=1)))
    assert len(ticks) == 2
    assert ticks[0].time < ticks[1].time
    with pytest.raises(ValueError, match="positive"):
        DukascopyHistoryClient(max_concurrency=0)
    with pytest.raises(ValueError, match="positive"):
        DukascopyHistoryClient(retries=0)


def test_resample_empty_and_invalid_timeframe() -> None:
    assert resample_midpoint_candles((), timeframe=timedelta(minutes=5)) == ()
    with pytest.raises(ValueError, match="positive"):
        resample_midpoint_candles((), timeframe=timedelta(0))


def test_gdelt_cached_records_and_response_validation(tmp_path) -> None:  # type: ignore[no-untyped-def]
    start = datetime(2026, 7, 1, tzinfo=UTC)
    end = start + timedelta(days=1)
    cache = tmp_path / "USD" / "20260701.json"
    cache.parent.mkdir(parents=True)
    cache.write_text(
        json.dumps(
            {
                "articles": [
                    {
                        "title": "Federal Reserve rates remain restrictive as inflation slows",
                        "seendate": "20260701T120000Z",
                        "url": "https://example.com/fed",
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    client = GdeltDocHistoryClient(cache_dir=tmp_path)
    records = asyncio.run(client.records(("USD",), start, end))
    assert len(records) == 1
    with pytest.raises(ValueError, match="unsupported"):
        asyncio.run(client.records(("XXX",), start, end))
    with pytest.raises(ValueError, match="object"):
        GdeltDocHistoryClient._parse_articles("USD", [], start, end)
    with pytest.raises(ValueError, match="list"):
        GdeltDocHistoryClient._parse_articles("USD", {"articles": {}}, start, end)


def test_resilient_gdelt_client_reads_dirty_cached_json(tmp_path) -> None:  # type: ignore[no-untyped-def]
    start = datetime(2026, 7, 1, tzinfo=UTC)
    end = start + timedelta(days=1)
    cache = tmp_path / "USD" / "20260701.json"
    cache.parent.mkdir(parents=True)
    cache.write_text(
        r'{"articles":[{"title":"Federal Reserve rate path C:\markets","seendate":"20260701T120000Z","url":"https://example.com"}]}',
        encoding="utf-8",
    )
    client = ResilientGdeltDocHistoryClient(cache_dir=tmp_path, max_concurrency=1)
    records = asyncio.run(client.records(("USD",), start, end))
    assert len(records) == 1
    with pytest.raises(ValueError, match="positive"):
        ResilientGdeltDocHistoryClient(max_concurrency=0)
