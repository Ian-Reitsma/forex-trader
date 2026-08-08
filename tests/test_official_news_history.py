from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

import pytest

from forex_trader.research.official_news_history import (
    OfficialFeedSpec,
    _parse_feed_datetime,
    official_feed_specs,
    official_news_observations,
    parse_official_feed,
)


START = datetime(2026, 6, 27, tzinfo=UTC)
END = datetime(2026, 8, 1, tzinfo=UTC)
SPEC = OfficialFeedSpec("USD", "Federal Reserve Board", "https://example.com/feed.xml", "fed-test")


def test_official_feed_registry_covers_three_pair_currencies() -> None:
    specs = official_feed_specs(("USD", "EUR", "GBP", "JPY"))
    assert {item.currency for item in specs} == {"USD", "EUR", "GBP", "JPY"}
    assert all(item.url.startswith("https://") for item in specs)
    with pytest.raises(ValueError, match="no official"):
        official_feed_specs(("CAD",))


def test_parse_rss_filters_period_and_irrelevant_items() -> None:
    payload = b"""<?xml version="1.0"?>
    <rss><channel>
      <item>
        <title>Federal Reserve issues FOMC statement on monetary policy</title>
        <description>Interest rates remain unchanged while inflation stays elevated.</description>
        <link>https://example.com/fomc</link>
        <pubDate>Wed, 29 Jul 2026 18:00:00 GMT</pubDate>
      </item>
      <item>
        <title>Federal Reserve office holiday schedule</title>
        <description>Administrative update.</description>
        <link>https://example.com/admin</link>
        <pubDate>Tue, 28 Jul 2026 14:00:00 GMT</pubDate>
      </item>
      <item>
        <title>Old monetary policy statement</title>
        <description>Interest rate decision.</description>
        <link>https://example.com/old</link>
        <pubDate>Wed, 17 Jun 2026 18:00:00 GMT</pubDate>
      </item>
    </channel></rss>"""
    records = parse_official_feed(payload, spec=SPEC, start=START, end=END)
    assert len(records) == 1
    assert records[0].seen_at == datetime(2026, 7, 29, 18, tzinfo=UTC)
    assert "inflation" in records[0].title.lower()
    assert records[0].domain == "example.com"


def test_parse_atom_handles_iso_timestamp_and_href() -> None:
    payload = b"""<?xml version="1.0" encoding="utf-8"?>
    <feed xmlns="http://www.w3.org/2005/Atom">
      <entry>
        <title>ECB monetary policy press conference</title>
        <summary>Economic outlook and inflation assessment.</summary>
        <link href="https://example.com/ecb"/>
        <updated>2026-07-23T12:30:00Z</updated>
      </entry>
    </feed>"""
    spec = OfficialFeedSpec("EUR", "European Central Bank", "https://example.com/ecb.xml", "ecb-test")
    records = parse_official_feed(payload, spec=spec, start=START, end=END)
    assert len(records) == 1
    assert records[0].url == "https://example.com/ecb"
    assert records[0].seen_at == datetime(2026, 7, 23, 12, 30, tzinfo=UTC)


def test_official_feed_rejects_bad_xml_and_time_ranges() -> None:
    with pytest.raises(ValueError, match="timezone-aware"):
        parse_official_feed(b"<rss/>", spec=SPEC, start=START.replace(tzinfo=None), end=END)
    with pytest.raises(ValueError, match="after start"):
        parse_official_feed(b"<rss/>", spec=SPEC, start=END, end=START)
    with pytest.raises(ValueError, match="invalid RSS"):
        parse_official_feed(b"<rss>", spec=SPEC, start=START, end=END)


def test_timestamp_parser_handles_rfc822_iso_and_date_only() -> None:
    assert _parse_feed_datetime("Wed, 29 Jul 2026 18:00:00 GMT") == datetime(2026, 7, 29, 18, tzinfo=UTC)
    assert _parse_feed_datetime("2026-07-29T18:00:00Z") == datetime(2026, 7, 29, 18, tzinfo=UTC)
    assert _parse_feed_datetime("2026-07-29") == datetime(2026, 7, 29, tzinfo=UTC)
    with pytest.raises(ValueError, match="unsupported"):
        _parse_feed_datetime("not-a-date")


def test_official_records_convert_to_high_provenance_pit_observations() -> None:
    payload = b"""<rss><channel><item>
      <title>Bank Rate maintained</title>
      <description>Monetary policy committee discusses inflation and growth.</description>
      <link>https://www.bankofengland.co.uk/example</link>
      <pubDate>Thu, 30 Jul 2026 11:00:00 GMT</pubDate>
    </item></channel></rss>"""
    spec = OfficialFeedSpec("GBP", "Bank of England", "https://example.com/boe.xml", "boe-test")
    records = parse_official_feed(payload, spec=spec, start=START, end=END)
    observations = official_news_observations(records)
    assert len(observations) == 1
    assert observations[0].currency == "GBP"
    assert observations[0].available_at == records[0].seen_at
    assert observations[0].source.startswith("official-central-bank:")
    assert observations[0].source_weight == Decimal("0.90")
    with pytest.raises(ValueError, match="source_weight"):
        official_news_observations(records, source_weight=Decimal("1.1"))
