from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from enum import StrEnum
from xml.etree import ElementTree

from forex_trader.ingestion.official_sources import OFFICIAL_MACRO_SOURCES, OfficialSourceClient, RawSourcePayload


FED_PRESS_RELEASES_RSS = "https://www.federalreserve.gov/feeds/press_all.xml"
ECB_PRESS_RSS = "https://www.ecb.europa.eu/rss/press.html"


class FeedFormat(StrEnum):
    RSS = "rss"
    ATOM = "atom"


@dataclass(frozen=True, slots=True)
class OfficialFeedDefinition:
    feed_id: str
    source_id: str
    url: str
    format: FeedFormat

    def __post_init__(self) -> None:
        if not self.feed_id.strip() or not self.source_id.strip():
            raise ValueError("feed_id and source_id are required")
        descriptor = OFFICIAL_MACRO_SOURCES.get(self.source_id)
        if descriptor is None:
            raise ValueError(f"unknown official source_id {self.source_id!r}")
        if not descriptor.permits(self.url):
            raise ValueError(f"feed URL is not permitted for official source {self.source_id}: {self.url}")


FED_PRESS_RELEASES = OfficialFeedDefinition(
    "federal_reserve_press_releases",
    "federal_reserve",
    FED_PRESS_RELEASES_RSS,
    FeedFormat.RSS,
)
ECB_PRESS_RELEASES = OfficialFeedDefinition(
    "ecb_press_speeches_transcripts",
    "ecb",
    ECB_PRESS_RSS,
    FeedFormat.RSS,
)


@dataclass(frozen=True, slots=True)
class DiscoveredOfficialDocument:
    feed_id: str
    source_id: str
    item_id: str
    title: str
    document_url: str
    published_at: datetime
    feed_record_id: str
    feed_payload_sha256: str
    summary: str = ""

    def __post_init__(self) -> None:
        if not all((self.feed_id.strip(), self.source_id.strip(), self.item_id.strip(), self.title.strip())):
            raise ValueError("discovered document identity fields are required")
        if self.published_at.tzinfo is None:
            raise ValueError("published_at must be timezone-aware")
        descriptor = OFFICIAL_MACRO_SOURCES.get(self.source_id)
        if descriptor is None or not descriptor.permits(self.document_url):
            raise ValueError("discovered document URL is not permitted for its official source")
        _require_sha256(self.feed_record_id, "feed_record_id")
        _require_sha256(self.feed_payload_sha256, "feed_payload_sha256")

    @property
    def discovery_id(self) -> str:
        raw = "\n".join(
            (
                self.feed_id,
                self.source_id,
                self.item_id,
                self.document_url,
                self.published_at.isoformat(),
                self.feed_record_id,
            )
        ).encode()
        return hashlib.sha256(raw).hexdigest()


@dataclass(frozen=True, slots=True)
class FeedDiscoveryResult:
    definition: OfficialFeedDefinition
    feed_payload: RawSourcePayload
    documents: tuple[DiscoveredOfficialDocument, ...]
    rejected_external_links: tuple[str, ...]

    def __post_init__(self) -> None:
        if self.feed_payload.source_id != self.definition.source_id:
            raise ValueError("feed payload source does not match feed definition")
        identities = [item.item_id for item in self.documents]
        if len(set(identities)) != len(identities):
            raise ValueError("official feed contains duplicate item identities")


@dataclass(frozen=True, slots=True)
class OfficialFeedDiscovery:
    definition: OfficialFeedDefinition
    client: OfficialSourceClient

    def __post_init__(self) -> None:
        if self.client.descriptor.source_id != self.definition.source_id:
            raise ValueError("feed discovery client source does not match feed definition")
        if self.client.descriptor != OFFICIAL_MACRO_SOURCES[self.definition.source_id]:
            raise ValueError("feed discovery requires the canonical official source descriptor")

    def fetch(self, *, retrieved_at: datetime) -> FeedDiscoveryResult:
        if retrieved_at.tzinfo is None:
            raise ValueError("retrieved_at must be timezone-aware")
        payload = self.client.fetch(
            self.definition.url,
            retrieved_at=retrieved_at,
            published_at=retrieved_at,
            available_at=retrieved_at,
        )
        return parse_official_feed(self.definition, payload)


def parse_official_feed(definition: OfficialFeedDefinition, payload: RawSourcePayload) -> FeedDiscoveryResult:
    if payload.source_id != definition.source_id:
        raise ValueError("feed payload source does not match feed definition")
    upper_body = payload.body.upper()
    if b"<!DOCTYPE" in upper_body or b"<!ENTITY" in upper_body:
        raise ValueError("official feed XML cannot contain DTD or entity declarations")
    try:
        root = ElementTree.fromstring(payload.body)
    except ElementTree.ParseError as exc:
        raise ValueError("official feed payload is not valid XML") from exc

    local_root = _local_name(root.tag)
    if definition.format is FeedFormat.RSS:
        if local_root != "rss":
            raise ValueError("official RSS feed root must be <rss>")
        raw_items = tuple(element for element in root.iter() if _local_name(element.tag) == "item")
        parser = _parse_rss_item
    else:
        if local_root != "feed":
            raise ValueError("official Atom feed root must be <feed>")
        raw_items = tuple(element for element in root if _local_name(element.tag) == "entry")
        parser = _parse_atom_entry

    documents: list[DiscoveredOfficialDocument] = []
    rejected: list[str] = []
    descriptor = OFFICIAL_MACRO_SOURCES[definition.source_id]
    for index, element in enumerate(raw_items):
        item_id, title, url, published_at, summary = parser(element, index)
        if not descriptor.permits(url):
            rejected.append(url)
            continue
        documents.append(
            DiscoveredOfficialDocument(
                feed_id=definition.feed_id,
                source_id=definition.source_id,
                item_id=item_id,
                title=title,
                document_url=url,
                published_at=published_at,
                feed_record_id=payload.record_id,
                feed_payload_sha256=payload.payload_sha256,
                summary=summary,
            )
        )
    return FeedDiscoveryResult(definition, payload, tuple(documents), tuple(rejected))


def _parse_rss_item(element: ElementTree.Element, index: int) -> tuple[str, str, str, datetime, str]:
    title = _required_child_text(element, "title", f"RSS item[{index}].title")
    url = _required_child_text(element, "link", f"RSS item[{index}].link")
    item_id = _optional_child_text(element, "guid") or url
    published = _required_child_text(element, "pubDate", f"RSS item[{index}].pubDate")
    summary = _optional_child_text(element, "description")
    try:
        published_at = parsedate_to_datetime(published)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"RSS item[{index}] has invalid pubDate") from exc
    if published_at.tzinfo is None:
        raise ValueError(f"RSS item[{index}] pubDate must include a timezone")
    return item_id, title, url, published_at.astimezone(UTC), summary


def _parse_atom_entry(element: ElementTree.Element, index: int) -> tuple[str, str, str, datetime, str]:
    title = _required_child_text(element, "title", f"Atom entry[{index}].title")
    item_id = _required_child_text(element, "id", f"Atom entry[{index}].id")
    url = ""
    for child in element:
        if _local_name(child.tag) != "link":
            continue
        rel = child.attrib.get("rel", "alternate")
        href = child.attrib.get("href", "").strip()
        if href and rel in {"", "alternate"}:
            url = href
            break
    if not url:
        raise ValueError(f"Atom entry[{index}] is missing an alternate link")
    published = _optional_child_text(element, "published") or _required_child_text(
        element,
        "updated",
        f"Atom entry[{index}].updated",
    )
    summary = _optional_child_text(element, "summary")
    published_at = _parse_iso_datetime(published, f"Atom entry[{index}] timestamp")
    return item_id, title, url, published_at, summary


def _parse_iso_datetime(value: str, name: str) -> datetime:
    normalized = value.strip().replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError as exc:
        raise ValueError(f"{name} is invalid") from exc
    if parsed.tzinfo is None:
        raise ValueError(f"{name} must include a timezone")
    return parsed.astimezone(UTC)


def _required_child_text(element: ElementTree.Element, name: str, field: str) -> str:
    value = _optional_child_text(element, name)
    if not value:
        raise ValueError(f"{field} is required")
    return value


def _optional_child_text(element: ElementTree.Element, name: str) -> str:
    for child in element:
        if _local_name(child.tag) == name:
            return (child.text or "").strip()
    return ""


def _local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _require_sha256(value: str, name: str) -> None:
    if len(value) != 64:
        raise ValueError(f"{name} must be a SHA-256 hex digest")
    try:
        int(value, 16)
    except ValueError as exc:
        raise ValueError(f"{name} must be a SHA-256 hex digest") from exc
