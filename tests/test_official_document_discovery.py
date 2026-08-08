from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

import pytest

from forex_trader.application.macro_ingestion import ProviderPollRunner
from forex_trader.application.official_document_discovery import OfficialDocumentDiscoveryOrchestrator
from forex_trader.domain.context import HealthState
from forex_trader.infrastructure.source_evidence_repository import SourceEvidenceRepository
from forex_trader.ingestion.official_feeds import (
    ECB_PRESS_RELEASES,
    FED_PRESS_RELEASES,
    FeedFormat,
    OfficialFeedDefinition,
    OfficialFeedDiscovery,
    parse_official_feed,
)
from forex_trader.ingestion.official_sources import (
    OFFICIAL_MACRO_SOURCES,
    HttpPayload,
    OfficialSourceClient,
    RawSourcePayload,
)


NOW = datetime(2026, 8, 8, 3, 0, tzinfo=UTC)

FED_RSS = b"""<?xml version='1.0' encoding='UTF-8'?>
<rss version='2.0'>
  <channel>
    <title>Federal Reserve Press Releases</title>
    <item>
      <title>Federal Reserve issues FOMC statement</title>
      <link>https://www.federalreserve.gov/newsevents/pressreleases/monetary20260729a.htm</link>
      <guid>https://www.federalreserve.gov/newsevents/pressreleases/monetary20260729a.htm</guid>
      <pubDate>Wed, 29 Jul 2026 18:00:00 GMT</pubDate>
      <description>FOMC statement</description>
    </item>
    <item>
      <title>External mirror should not be followed</title>
      <link>https://mirror.example/fed-copy</link>
      <guid>mirror-1</guid>
      <pubDate>Wed, 29 Jul 2026 18:00:01 GMT</pubDate>
    </item>
  </channel>
</rss>
"""

ECB_RSS = b"""<?xml version='1.0' encoding='UTF-8'?>
<rss version='2.0'>
  <channel>
    <title>ECB press feed</title>
    <item>
      <title>Monetary policy decisions</title>
      <link>https://www.ecb.europa.eu/press/pr/date/2026/html/ecb.mp260723~abc123.en.html</link>
      <guid>ecb-mp-2026-07-23</guid>
      <pubDate>Thu, 23 Jul 2026 12:15:00 +0000</pubDate>
      <description>ECB monetary policy decisions</description>
    </item>
  </channel>
</rss>
"""

ATOM = b"""<?xml version='1.0' encoding='UTF-8'?>
<feed xmlns='http://www.w3.org/2005/Atom'>
  <title>Official feed</title>
  <entry>
    <id>entry-1</id>
    <title>Policy statement</title>
    <updated>2026-07-23T12:15:00Z</updated>
    <link rel='alternate' href='https://www.ecb.europa.eu/press/pr/date/2026/html/example.en.html'/>
    <summary>Statement summary</summary>
  </entry>
</feed>
"""


class Transport:
    def __init__(self, body: bytes, final_url: str) -> None:
        self.body = body
        self.final_url = final_url
        self.calls: list[str] = []

    def get(self, url: str, *, timeout_seconds: float) -> HttpPayload:
        assert timeout_seconds > 0
        self.calls.append(url)
        return HttpPayload(200, {"content-type": "application/rss+xml"}, self.body, self.final_url)


def feed_payload(definition: OfficialFeedDefinition, body: bytes) -> RawSourcePayload:
    descriptor = OFFICIAL_MACRO_SOURCES[definition.source_id]
    return RawSourcePayload.create(
        descriptor=descriptor,
        url=definition.url,
        body=body,
        content_type="application/rss+xml",
        retrieved_at=NOW,
        published_at=NOW,
        available_at=NOW,
    )


def test_verified_feed_definitions_use_canonical_official_sources() -> None:
    assert FED_PRESS_RELEASES.source_id == "federal_reserve"
    assert FED_PRESS_RELEASES.url == "https://www.federalreserve.gov/feeds/press_all.xml"
    assert ECB_PRESS_RELEASES.source_id == "ecb"
    assert ECB_PRESS_RELEASES.url == "https://www.ecb.europa.eu/rss/press.html"

    with pytest.raises(ValueError, match="unknown official"):
        OfficialFeedDefinition("x", "unknown", "https://unknown.example/feed", FeedFormat.RSS)
    with pytest.raises(ValueError, match="not permitted"):
        OfficialFeedDefinition("x", "ecb", "https://evil.example/feed", FeedFormat.RSS)


def test_fed_rss_discovery_keeps_first_party_document_and_records_external_rejection() -> None:
    result = parse_official_feed(FED_PRESS_RELEASES, feed_payload(FED_PRESS_RELEASES, FED_RSS))
    assert len(result.documents) == 1
    item = result.documents[0]
    assert item.source_id == "federal_reserve"
    assert item.item_id.endswith("monetary20260729a.htm")
    assert item.title == "Federal Reserve issues FOMC statement"
    assert item.published_at == datetime(2026, 7, 29, 18, 0, tzinfo=UTC)
    assert item.feed_record_id == result.feed_payload.record_id
    assert item.feed_payload_sha256 == result.feed_payload.payload_sha256
    assert len(item.discovery_id) == 64
    assert result.rejected_external_links == ("https://mirror.example/fed-copy",)


def test_ecb_rss_discovery_parses_official_document_identity() -> None:
    result = parse_official_feed(ECB_PRESS_RELEASES, feed_payload(ECB_PRESS_RELEASES, ECB_RSS))
    assert len(result.documents) == 1
    item = result.documents[0]
    assert item.item_id == "ecb-mp-2026-07-23"
    assert item.document_url.startswith("https://www.ecb.europa.eu/")
    assert item.published_at == datetime(2026, 7, 23, 12, 15, tzinfo=UTC)
    assert item.summary == "ECB monetary policy decisions"


def test_atom_parser_supports_namespaces_and_iso_timestamps() -> None:
    definition = OfficialFeedDefinition("ecb-atom-test", "ecb", ECB_PRESS_RELEASES.url, FeedFormat.ATOM)
    result = parse_official_feed(definition, feed_payload(definition, ATOM))
    assert len(result.documents) == 1
    item = result.documents[0]
    assert item.item_id == "entry-1"
    assert item.published_at == datetime(2026, 7, 23, 12, 15, tzinfo=UTC)
    assert item.summary == "Statement summary"


def test_feed_discovery_fetches_via_canonical_official_client() -> None:
    transport = Transport(FED_RSS, FED_PRESS_RELEASES.url)
    client = OfficialSourceClient(OFFICIAL_MACRO_SOURCES["federal_reserve"], transport)
    discovery = OfficialFeedDiscovery(FED_PRESS_RELEASES, client)
    result = discovery.fetch(retrieved_at=NOW)
    assert result.feed_payload.retrieved_at == NOW
    assert result.feed_payload.available_at == NOW
    assert transport.calls == [FED_PRESS_RELEASES.url]

    ecb_client = OfficialSourceClient(OFFICIAL_MACRO_SOURCES["ecb"], Transport(ECB_RSS, ECB_PRESS_RELEASES.url))
    with pytest.raises(ValueError, match="client source"):
        OfficialFeedDiscovery(FED_PRESS_RELEASES, ecb_client)


def test_document_discovery_orchestrator_persists_feed_and_health(tmp_path) -> None:
    repository = SourceEvidenceRepository(tmp_path / "sources.db")
    transport = Transport(FED_RSS, FED_PRESS_RELEASES.url)
    discovery = OfficialFeedDiscovery(
        FED_PRESS_RELEASES,
        OfficialSourceClient(OFFICIAL_MACRO_SOURCES["federal_reserve"], transport),
    )
    orchestrator = OfficialDocumentDiscoveryOrchestrator(repository, ProviderPollRunner(repository))
    result = orchestrator.poll(discovery, observed_at=NOW)

    assert repository.payload(result.feed_payload.record_id) == result.feed_payload
    health = repository.latest_health(
        "federal_reserve",
        as_of=NOW,
        maximum_age_seconds=Decimal("60"),
    )
    assert health.state is HealthState.HEALTHY
    assert len(result.documents) == 1


def test_feed_parser_rejects_wrong_root_malformed_xml_missing_required_fields_and_duplicate_ids() -> None:
    with pytest.raises(ValueError, match="valid XML"):
        parse_official_feed(FED_PRESS_RELEASES, feed_payload(FED_PRESS_RELEASES, b"<rss>"))
    with pytest.raises(ValueError, match="root"):
        parse_official_feed(FED_PRESS_RELEASES, feed_payload(FED_PRESS_RELEASES, b"<feed/>"))

    missing = b"<rss><channel><item><title>x</title></item></channel></rss>"
    with pytest.raises(ValueError, match="link"):
        parse_official_feed(FED_PRESS_RELEASES, feed_payload(FED_PRESS_RELEASES, missing))

    duplicate = b"""<rss><channel>
      <item><title>A</title><link>https://www.federalreserve.gov/a</link><guid>same</guid><pubDate>Wed, 29 Jul 2026 18:00:00 GMT</pubDate></item>
      <item><title>B</title><link>https://www.federalreserve.gov/b</link><guid>same</guid><pubDate>Wed, 29 Jul 2026 18:00:01 GMT</pubDate></item>
    </channel></rss>"""
    with pytest.raises(ValueError, match="duplicate"):
        parse_official_feed(FED_PRESS_RELEASES, feed_payload(FED_PRESS_RELEASES, duplicate))


def test_feed_parser_rejects_bad_rss_and_atom_timestamps_and_missing_atom_link() -> None:
    bad_rss_date = b"""<rss><channel><item><title>A</title><link>https://www.federalreserve.gov/a</link><pubDate>not-a-date</pubDate></item></channel></rss>"""
    with pytest.raises(ValueError, match="invalid pubDate"):
        parse_official_feed(FED_PRESS_RELEASES, feed_payload(FED_PRESS_RELEASES, bad_rss_date))

    atom_definition = OfficialFeedDefinition("ecb-atom-test", "ecb", ECB_PRESS_RELEASES.url, FeedFormat.ATOM)
    bad_atom_link = b"""<feed xmlns='http://www.w3.org/2005/Atom'><entry><id>x</id><title>A</title><updated>2026-07-23T12:15:00Z</updated></entry></feed>"""
    with pytest.raises(ValueError, match="alternate link"):
        parse_official_feed(atom_definition, feed_payload(atom_definition, bad_atom_link))

    bad_atom_date = b"""<feed xmlns='http://www.w3.org/2005/Atom'><entry><id>x</id><title>A</title><updated>not-a-date</updated><link href='https://www.ecb.europa.eu/a'/></entry></feed>"""
    with pytest.raises(ValueError, match="timestamp is invalid"):
        parse_official_feed(atom_definition, feed_payload(atom_definition, bad_atom_date))


def test_discovered_document_rejects_bad_hash_provenance_and_orchestrator_naive_time(tmp_path) -> None:
    result = parse_official_feed(FED_PRESS_RELEASES, feed_payload(FED_PRESS_RELEASES, FED_RSS))
    item = result.documents[0]
    with pytest.raises(ValueError, match="feed_record_id"):
        type(item)(
            feed_id=item.feed_id,
            source_id=item.source_id,
            item_id=item.item_id,
            title=item.title,
            document_url=item.document_url,
            published_at=item.published_at,
            feed_record_id="bad",
            feed_payload_sha256=item.feed_payload_sha256,
        )

    repository = SourceEvidenceRepository(tmp_path / "sources.db")
    discovery = OfficialFeedDiscovery(
        FED_PRESS_RELEASES,
        OfficialSourceClient(OFFICIAL_MACRO_SOURCES["federal_reserve"], Transport(FED_RSS, FED_PRESS_RELEASES.url)),
    )
    orchestrator = OfficialDocumentDiscoveryOrchestrator(repository, ProviderPollRunner(repository))
    with pytest.raises(ValueError, match="timezone-aware"):
        orchestrator.poll(discovery, observed_at=NOW.replace(tzinfo=None))
