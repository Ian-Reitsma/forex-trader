from __future__ import annotations

import lzma
import struct
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from forex_trader.research.public_history import (
    GdeltDocHistoryClient,
    HistoricalTick,
    decode_dukascopy_bi5,
    dukascopy_hour_url,
    dukascopy_price_divisor,
    gdelt_news_observations,
    resample_midpoint_candles,
)


def _bi5(*rows: tuple[int, int, int, float, float]) -> bytes:
    raw = b"".join(struct.pack(">3I2f", *row) for row in rows)
    return lzma.compress(raw)


def test_dukascopy_url_uses_zero_indexed_month_and_pair_symbol() -> None:
    instant = datetime(2026, 7, 14, 9, tzinfo=UTC)
    assert dukascopy_hour_url("EUR_USD", instant).endswith("/EURUSD/2026/06/14/09h_ticks.bi5")
    assert dukascopy_price_divisor("EUR_USD") == Decimal("100000")
    assert dukascopy_price_divisor("USD_JPY") == Decimal("1000")


def test_decode_dukascopy_bi5_preserves_exact_bid_ask_and_time() -> None:
    hour = datetime(2026, 7, 14, 9, tzinfo=UTC)
    payload = _bi5(
        (250, 110025, 110020, 1.5, 2.5),
        (1250, 110030, 110024, 1.0, 1.25),
    )
    ticks = decode_dukascopy_bi5(payload, instrument="EUR_USD", hour_start=hour)
    assert ticks[0].time == hour + timedelta(milliseconds=250)
    assert ticks[0].ask == Decimal("1.10025")
    assert ticks[0].bid == Decimal("1.1002")
    assert ticks[1].spread == Decimal("0.00006")
    assert ticks[0].ask_volume > 0
    assert ticks[0].bid_volume > 0


def test_decode_jpy_pair_uses_three_decimal_price_scale() -> None:
    hour = datetime(2026, 7, 14, 9, tzinfo=UTC)
    ticks = decode_dukascopy_bi5(
        _bi5((100, 157125, 157117, 1.0, 1.0)),
        instrument="USD_JPY",
        hour_start=hour,
    )
    assert ticks[0].ask == Decimal("157.125")
    assert ticks[0].bid == Decimal("157.117")


def test_decode_rejects_corrupt_or_crossed_payloads() -> None:
    hour = datetime(2026, 7, 14, 9, tzinfo=UTC)
    with pytest.raises(ValueError, match="LZMA"):
        decode_dukascopy_bi5(b"not-lzma", instrument="EUR_USD", hour_start=hour)
    with pytest.raises(ValueError, match="ask"):
        decode_dukascopy_bi5(
            _bi5((100, 110000, 110010, 1.0, 1.0)),
            instrument="EUR_USD",
            hour_start=hour,
        )


def test_tick_resampling_builds_midpoint_candles_without_inventing_spread() -> None:
    base = datetime(2026, 7, 14, 9, tzinfo=UTC)
    ticks = (
        HistoricalTick("EUR_USD", base, Decimal("1.1000"), Decimal("1.1002")),
        HistoricalTick("EUR_USD", base + timedelta(minutes=2), Decimal("1.1004"), Decimal("1.1006")),
        HistoricalTick("EUR_USD", base + timedelta(minutes=5), Decimal("1.0998"), Decimal("1.1000")),
    )
    candles = resample_midpoint_candles(ticks, timeframe=timedelta(minutes=5))
    assert len(candles) == 2
    assert candles[0].open == Decimal("1.1001")
    assert candles[0].high == Decimal("1.1005")
    assert candles[0].close == Decimal("1.1005")
    assert candles[0].volume == 2
    assert candles[1].open == Decimal("1.0999")


def test_gdelt_parser_filters_irrelevant_titles_and_keeps_seen_time() -> None:
    start = datetime(2026, 7, 14, tzinfo=UTC)
    end = start + timedelta(days=1)
    payload = {
        "articles": [
            {
                "title": "Federal Reserve rate cut debate intensifies as inflation cools",
                "seendate": "20260714T153000Z",
                "url": "https://example.com/fed",
                "domain": "example.com",
            },
            {
                "title": "Local sports team wins match",
                "seendate": "20260714T160000Z",
                "url": "https://example.com/sport",
            },
        ]
    }
    records = GdeltDocHistoryClient._parse_articles("USD", payload, start, end)
    assert len(records) == 1
    assert records[0].seen_at == datetime(2026, 7, 14, 15, 30, tzinfo=UTC)
    observations = gdelt_news_observations(records)
    assert observations[0].currency == "USD"
    assert observations[0].available_at == records[0].seen_at
    assert observations[0].source == "gdelt-doc-2.0"
