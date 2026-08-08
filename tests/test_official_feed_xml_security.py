from __future__ import annotations

from datetime import UTC, datetime

import pytest

from forex_trader.ingestion.official_feeds import FED_PRESS_RELEASES, parse_official_feed
from forex_trader.ingestion.official_sources import OFFICIAL_MACRO_SOURCES, RawSourcePayload


NOW = datetime(2026, 8, 8, 3, 0, tzinfo=UTC)


def _payload(body: bytes) -> RawSourcePayload:
    return RawSourcePayload.create(
        descriptor=OFFICIAL_MACRO_SOURCES["federal_reserve"],
        url=FED_PRESS_RELEASES.url,
        body=body,
        content_type="application/rss+xml",
        retrieved_at=NOW,
        published_at=NOW,
        available_at=NOW,
    )


def test_official_feed_rejects_doctype_and_entity_declarations_before_xml_parse() -> None:
    malicious = b"""<?xml version='1.0'?>
<!DOCTYPE rss [<!ENTITY x 'expanded'>]>
<rss><channel><item><title>&x;</title><link>https://www.federalreserve.gov/a</link><pubDate>Wed, 29 Jul 2026 18:00:00 GMT</pubDate></item></channel></rss>
"""
    with pytest.raises(ValueError, match="DTD or entity"):
        parse_official_feed(FED_PRESS_RELEASES, _payload(malicious))
