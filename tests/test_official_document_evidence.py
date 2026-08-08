from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from forex_trader.application.macro_ingestion import ProviderPollRunner
from forex_trader.application.official_document_evidence import OfficialDocumentEvidenceOrchestrator
from forex_trader.domain.context import HealthState
from forex_trader.infrastructure.official_document_repository import OfficialDocumentRepository
from forex_trader.infrastructure.source_evidence_repository import SourceEvidenceRepository
from forex_trader.ingestion.official_feeds import DiscoveredOfficialDocument
from forex_trader.ingestion.official_sources import (
    OFFICIAL_MACRO_SOURCES,
    HttpPayload,
    OfficialSourceClient,
    RawSourcePayload,
    SourceAuthority,
    SourceDescriptor,
)
from forex_trader.intelligence.official_documents import (
    DocumentTextChange,
    OfficialDocumentFamily,
    build_document_version,
    compare_document_versions,
    extract_official_document_text,
)


NOW = datetime(2026, 8, 8, 4, 0, tzinfo=UTC)
FED = OFFICIAL_MACRO_SOURCES["federal_reserve"]
FEED_RECORD = "a" * 64
FEED_PAYLOAD = "b" * 64


HTML_FIRST = b"""<!DOCTYPE html>
<html>
<head><title>Ignored browser title</title><style>.x{display:none}</style></head>
<body>
<nav>Ignored navigation</nav>
<main>
  <h1>Federal Reserve issues FOMC statement</h1>
  <p>The Committee decided to maintain the target range.</p>
  <p>Inflation remains somewhat elevated.</p>
  <script>ignoredScript()</script>
</main>
<footer>Ignored footer</footer>
</body>
</html>
"""

HTML_SECOND = b"""<!DOCTYPE html>
<html><body><main>
<h1>Federal Reserve issues FOMC statement</h1>
<p>The Committee decided to lower the target range.</p>
<p>Inflation has moved closer to the Committee's objective.</p>
<p>The Committee will carefully assess incoming data.</p>
</main></body></html>
"""


class SequenceTransport:
    def __init__(self, bodies: list[bytes]) -> None:
        self.bodies = bodies
        self.calls: list[str] = []

    def get(self, url: str, *, timeout_seconds: float) -> HttpPayload:
        assert timeout_seconds > 0
        self.calls.append(url)
        if not self.bodies:
            raise AssertionError("unexpected document fetch")
        return HttpPayload(200, {"content-type": "text/html; charset=utf-8"}, self.bodies.pop(0), url)


def family() -> OfficialDocumentFamily:
    return OfficialDocumentFamily(
        "fed_fomc_statement",
        "federal_reserve",
        "monetary_policy_statement",
        "Federal Reserve",
        "USD",
    )


def discovery(index: int = 1) -> DiscoveredOfficialDocument:
    published = NOW + timedelta(minutes=index)
    url = f"https://www.federalreserve.gov/newsevents/pressreleases/monetary2026080{index}a.htm"
    return DiscoveredOfficialDocument(
        feed_id="federal_reserve_press_releases",
        source_id="federal_reserve",
        item_id=f"fomc-{index}",
        title="Federal Reserve issues FOMC statement",
        document_url=url,
        published_at=published,
        feed_record_id=FEED_RECORD,
        feed_payload_sha256=FEED_PAYLOAD,
    )


def raw_html(body: bytes, *, url: str, at: datetime) -> RawSourcePayload:
    return RawSourcePayload.create(
        descriptor=FED,
        url=url,
        body=body,
        content_type="text/html",
        retrieved_at=at,
        published_at=at - timedelta(minutes=1),
        available_at=at,
    )


def test_html_extraction_is_deterministic_visible_text_and_accepts_standard_doctype() -> None:
    source = raw_html(HTML_FIRST, url=discovery().document_url, at=NOW + timedelta(minutes=2))
    extracted = extract_official_document_text(source)
    assert extracted.paragraphs == (
        "Federal Reserve issues FOMC statement",
        "The Committee decided to maintain the target range.",
        "Inflation remains somewhat elevated.",
    )
    assert "Ignored" not in extracted.text
    assert "ignoredScript" not in extracted.text
    assert len(extracted.text_sha256) == 64


def test_plain_text_extraction_and_content_failures() -> None:
    plain = RawSourcePayload.create(
        descriptor=FED,
        url=discovery().document_url,
        body=b" First paragraph. \n\n Second   paragraph. ",
        content_type="text/plain",
        retrieved_at=NOW + timedelta(minutes=2),
        published_at=NOW,
        available_at=NOW + timedelta(minutes=2),
    )
    extracted = extract_official_document_text(plain)
    assert extracted.paragraphs == ("First paragraph.", "Second paragraph.")

    licensed = SourceDescriptor("licensed", "Vendor", SourceAuthority.LICENSED, frozenset({"vendor.example"}))
    licensed_payload = RawSourcePayload.create(
        descriptor=licensed,
        url="https://vendor.example/x",
        body=b"text",
        content_type="text/plain",
        retrieved_at=NOW,
        published_at=NOW,
        available_at=NOW,
    )
    with pytest.raises(ValueError, match="OFFICIAL"):
        extract_official_document_text(licensed_payload)

    unsupported = RawSourcePayload.create(
        descriptor=FED,
        url=discovery().document_url,
        body=b"%PDF",
        content_type="application/pdf",
        retrieved_at=NOW + timedelta(minutes=2),
        published_at=NOW,
        available_at=NOW + timedelta(minutes=2),
    )
    with pytest.raises(ValueError, match="unsupported"):
        extract_official_document_text(unsupported)

    bad_utf8 = RawSourcePayload.create(
        descriptor=FED,
        url=discovery().document_url,
        body=b"\xff\xfe",
        content_type="text/plain",
        retrieved_at=NOW + timedelta(minutes=2),
        published_at=NOW,
        available_at=NOW + timedelta(minutes=2),
    )
    with pytest.raises(ValueError, match="UTF-8"):
        extract_official_document_text(bad_utf8)

    entity = raw_html(
        b"<html><body><!ENTITY x 'bad'><p>Text</p></body></html>",
        url=discovery().document_url,
        at=NOW + timedelta(minutes=2),
    )
    with pytest.raises(ValueError, match="entity declarations"):
        extract_official_document_text(entity)


def test_family_is_explicit_and_cannot_be_assigned_across_sources() -> None:
    with pytest.raises(ValueError, match="three-letter"):
        OfficialDocumentFamily("x", "federal_reserve", "statement", "Federal Reserve", "US")
    ecb_document = DiscoveredOfficialDocument(
        feed_id="ecb",
        source_id="ecb",
        item_id="ecb-1",
        title="Monetary policy decisions",
        document_url="https://www.ecb.europa.eu/press/pr/date/2026/html/example.en.html",
        published_at=NOW,
        feed_record_id=FEED_RECORD,
        feed_payload_sha256=FEED_PAYLOAD,
    )
    with pytest.raises(ValueError, match="explicit document family"):
        family().validate_discovery(ecb_document)


def test_version_build_and_diff_emit_exact_added_removed_paragraph_evidence() -> None:
    first_discovery = discovery(1)
    second_discovery = discovery(2)
    first_source = raw_html(HTML_FIRST, url=first_discovery.document_url, at=NOW + timedelta(minutes=3))
    second_source = raw_html(HTML_SECOND, url=second_discovery.document_url, at=NOW + timedelta(minutes=4))
    first_text = extract_official_document_text(first_source)
    second_text = extract_official_document_text(second_source)
    first = build_document_version(family(), first_discovery, first_source, first_text, predecessor_version_id=None)
    second = build_document_version(
        family(),
        second_discovery,
        second_source,
        second_text,
        predecessor_version_id=first.version_id,
    )
    diff = compare_document_versions(first, second)
    assert diff.changed is True
    assert [item.text for item in diff.removed] == [
        "The Committee decided to maintain the target range.",
        "Inflation remains somewhat elevated.",
    ]
    assert [item.text for item in diff.added] == [
        "The Committee decided to lower the target range.",
        "Inflation has moved closer to the Committee's objective.",
        "The Committee will carefully assess incoming data.",
    ]
    assert all(len(item.text_sha256) == 64 for item in diff.added + diff.removed)

    wrong = build_document_version(
        OfficialDocumentFamily("other-family", "federal_reserve", "statement", "Federal Reserve", "USD"),
        second_discovery,
        second_source,
        second_text,
        predecessor_version_id=None,
    )
    with pytest.raises(ValueError, match="different explicit families"):
        compare_document_versions(first, wrong)


def test_document_repository_enforces_latest_predecessor_and_point_in_time(tmp_path) -> None:
    repository = OfficialDocumentRepository(tmp_path / "documents.db")
    first_discovery = discovery(1)
    second_discovery = discovery(2)
    first_source = raw_html(HTML_FIRST, url=first_discovery.document_url, at=NOW + timedelta(minutes=3))
    second_source = raw_html(HTML_SECOND, url=second_discovery.document_url, at=NOW + timedelta(minutes=4))
    first = build_document_version(
        family(),
        first_discovery,
        first_source,
        extract_official_document_text(first_source),
        predecessor_version_id=None,
    )
    assert repository.append(first) is True
    assert repository.append(first) is False
    assert repository.latest(first.family_id) == first
    assert repository.as_of(first.family_id, first.available_at - timedelta(seconds=1)) is None
    assert repository.as_of(first.family_id, first.available_at) == first

    second = build_document_version(
        family(),
        second_discovery,
        second_source,
        extract_official_document_text(second_source),
        predecessor_version_id=first.version_id,
    )
    assert repository.append(second) is True
    assert repository.latest(first.family_id) == second
    assert repository.equivalent(
        family_id=second.family_id,
        discovery_id=second.discovery_id,
        source_payload_sha256=second.source_payload_sha256,
        text_sha256=second.text_sha256,
    ) == second

    bad_predecessor = build_document_version(
        family(),
        discovery(3),
        raw_html(HTML_SECOND, url=discovery(3).document_url, at=NOW + timedelta(minutes=5)),
        extract_official_document_text(
            raw_html(HTML_SECOND, url=discovery(3).document_url, at=NOW + timedelta(minutes=5))
        ),
        predecessor_version_id=first.version_id,
    )
    with pytest.raises(ValueError, match="latest family version"):
        repository.append(bad_predecessor)


def test_document_evidence_orchestrator_persists_body_builds_lineage_diff_and_is_idempotent(tmp_path) -> None:
    source_repository = SourceEvidenceRepository(tmp_path / "source.db")
    document_repository = OfficialDocumentRepository(tmp_path / "documents.db")
    transport = SequenceTransport([HTML_FIRST, HTML_SECOND, HTML_SECOND])
    client = OfficialSourceClient(FED, transport)
    orchestrator = OfficialDocumentEvidenceOrchestrator(
        source_repository,
        document_repository,
        ProviderPollRunner(source_repository),
    )

    first = orchestrator.ingest(family(), discovery(1), client, retrieved_at=NOW + timedelta(minutes=3))
    assert first.version_inserted is True
    assert first.diff is None
    assert source_repository.payload(first.version.source_record_id) is not None
    assert document_repository.get(first.version.version_id) == first.version

    second = orchestrator.ingest(family(), discovery(2), client, retrieved_at=NOW + timedelta(minutes=4))
    assert second.version_inserted is True
    assert second.diff is not None and second.diff.changed is True
    assert second.version.predecessor_version_id == first.version.version_id

    repeated = orchestrator.ingest(family(), discovery(2), client, retrieved_at=NOW + timedelta(minutes=5))
    assert repeated.version_inserted is False
    assert repeated.version.version_id == second.version.version_id
    assert repeated.diff is None
    health = source_repository.latest_health(
        "federal_reserve",
        as_of=NOW + timedelta(minutes=5),
        maximum_age_seconds=Decimal("60"),
    )
    assert health.state is HealthState.HEALTHY


def test_orchestrator_rejects_naive_time_wrong_client_and_prepublication_fetch(tmp_path) -> None:
    source_repository = SourceEvidenceRepository(tmp_path / "source.db")
    document_repository = OfficialDocumentRepository(tmp_path / "documents.db")
    orchestrator = OfficialDocumentEvidenceOrchestrator(
        source_repository,
        document_repository,
        ProviderPollRunner(source_repository),
    )
    fed_client = OfficialSourceClient(FED, SequenceTransport([HTML_FIRST]))
    with pytest.raises(ValueError, match="timezone-aware"):
        orchestrator.ingest(family(), discovery(1), fed_client, retrieved_at=NOW.replace(tzinfo=None))
    with pytest.raises(ValueError, match="before its discovered publication"):
        orchestrator.ingest(family(), discovery(1), fed_client, retrieved_at=NOW)

    ecb_client = OfficialSourceClient(
        OFFICIAL_MACRO_SOURCES["ecb"],
        SequenceTransport([HTML_FIRST]),
    )
    with pytest.raises(ValueError, match="client source"):
        orchestrator.ingest(family(), discovery(1), ecb_client, retrieved_at=NOW + timedelta(minutes=3))


def test_text_change_validates_hash_and_side() -> None:
    change = DocumentTextChange.create("added", 0, "New language.")
    assert len(change.text_sha256) == 64
    with pytest.raises(ValueError, match="added or removed"):
        DocumentTextChange("changed", 0, "x", change.text_sha256)
