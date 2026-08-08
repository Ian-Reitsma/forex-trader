from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from datetime import datetime
from difflib import SequenceMatcher
from html.parser import HTMLParser

from forex_trader.ingestion.official_feeds import DiscoveredOfficialDocument
from forex_trader.ingestion.official_sources import RawSourcePayload, SourceAuthority


_WHITESPACE = re.compile(r"[ \t\r\f\v]+")
_BLOCK_TAGS = frozenset(
    {
        "address",
        "article",
        "blockquote",
        "br",
        "dd",
        "div",
        "dl",
        "dt",
        "h1",
        "h2",
        "h3",
        "h4",
        "h5",
        "h6",
        "hr",
        "li",
        "main",
        "p",
        "section",
        "td",
        "th",
        "tr",
    }
)
_EXCLUDED_TAGS = frozenset({"aside", "button", "footer", "form", "head", "nav", "noscript", "script", "style", "svg"})


@dataclass(frozen=True, slots=True)
class OfficialDocumentFamily:
    family_id: str
    source_id: str
    document_type: str
    institution: str
    currency: str

    def __post_init__(self) -> None:
        if any(
            not item.strip()
            for item in (self.family_id, self.source_id, self.document_type, self.institution, self.currency)
        ):
            raise ValueError("official document family identity fields are required")
        if len(self.currency.strip()) != 3:
            raise ValueError("official document family currency must be a three-letter code")

    def validate_discovery(self, document: DiscoveredOfficialDocument) -> None:
        if document.source_id != self.source_id:
            raise ValueError("discovered document source does not match explicit document family")


@dataclass(frozen=True, slots=True)
class ExtractedDocumentText:
    text: str
    text_sha256: str
    paragraphs: tuple[str, ...]

    def __post_init__(self) -> None:
        if not self.text.strip() or not self.paragraphs:
            raise ValueError("extracted official document text cannot be empty")
        if hashlib.sha256(self.text.encode()).hexdigest() != self.text_sha256:
            raise ValueError("text_sha256 does not match extracted text")
        if self.paragraphs != tuple(line for line in self.text.split("\n") if line):
            raise ValueError("paragraphs must exactly match normalized document text")


@dataclass(frozen=True, slots=True)
class OfficialDocumentVersion:
    family_id: str
    source_id: str
    document_type: str
    institution: str
    currency: str
    discovery_id: str
    item_id: str
    document_url: str
    published_at: datetime
    available_at: datetime
    source_record_id: str
    source_payload_sha256: str
    text_sha256: str
    text: str
    predecessor_version_id: str | None = None

    def __post_init__(self) -> None:
        required = (
            self.family_id,
            self.source_id,
            self.document_type,
            self.institution,
            self.currency,
            self.discovery_id,
            self.item_id,
            self.document_url,
            self.source_record_id,
            self.source_payload_sha256,
            self.text_sha256,
        )
        if any(not item.strip() for item in required):
            raise ValueError("official document version identity fields are required")
        if self.published_at.tzinfo is None or self.available_at.tzinfo is None:
            raise ValueError("official document version timestamps must be timezone-aware")
        if self.available_at < self.published_at:
            raise ValueError("document available_at cannot precede published_at")
        if len(self.currency.strip()) != 3:
            raise ValueError("official document version currency must be a three-letter code")
        for value, name in (
            (self.discovery_id, "discovery_id"),
            (self.source_record_id, "source_record_id"),
            (self.source_payload_sha256, "source_payload_sha256"),
            (self.text_sha256, "text_sha256"),
        ):
            _require_sha256(value, name)
        if self.predecessor_version_id is not None:
            _require_sha256(self.predecessor_version_id, "predecessor_version_id")
        if hashlib.sha256(self.text.encode()).hexdigest() != self.text_sha256:
            raise ValueError("document text SHA-256 does not match text")

    @property
    def version_id(self) -> str:
        payload = "\n".join(
            (
                self.family_id,
                self.source_id,
                self.discovery_id,
                self.item_id,
                self.document_url,
                self.published_at.isoformat(),
                self.available_at.isoformat(),
                self.source_record_id,
                self.source_payload_sha256,
                self.text_sha256,
                self.predecessor_version_id or "",
            )
        ).encode()
        return hashlib.sha256(payload).hexdigest()

    @property
    def paragraphs(self) -> tuple[str, ...]:
        return tuple(line for line in self.text.split("\n") if line)


@dataclass(frozen=True, slots=True)
class DocumentTextChange:
    side: str
    paragraph_index: int
    text: str
    text_sha256: str

    def __post_init__(self) -> None:
        if self.side not in {"added", "removed"}:
            raise ValueError("document text change side must be added or removed")
        if self.paragraph_index < 0 or not self.text.strip():
            raise ValueError("document text change requires a non-negative index and text")
        if hashlib.sha256(self.text.encode()).hexdigest() != self.text_sha256:
            raise ValueError("document text change hash does not match text")

    @classmethod
    def create(cls, side: str, paragraph_index: int, text: str) -> DocumentTextChange:
        return cls(side, paragraph_index, text, hashlib.sha256(text.encode()).hexdigest())


@dataclass(frozen=True, slots=True)
class OfficialDocumentDiff:
    family_id: str
    previous_version_id: str
    current_version_id: str
    added: tuple[DocumentTextChange, ...]
    removed: tuple[DocumentTextChange, ...]

    @property
    def changed(self) -> bool:
        return bool(self.added or self.removed)


def extract_official_document_text(payload: RawSourcePayload) -> ExtractedDocumentText:
    if payload.authority is not SourceAuthority.OFFICIAL:
        raise ValueError("official document extraction requires OFFICIAL source authority")
    content_type = payload.content_type.lower()
    if content_type in {"text/html", "application/xhtml+xml"}:
        text = _extract_html(payload.body)
    elif content_type.startswith("text/plain"):
        text = _decode_utf8(payload.body)
    else:
        raise ValueError(f"unsupported official document content type: {payload.content_type}")
    normalized = _normalize_visible_text(text)
    paragraphs = tuple(line for line in normalized.split("\n") if line)
    if not paragraphs:
        raise ValueError("official document contains no extractable visible text")
    return ExtractedDocumentText(normalized, hashlib.sha256(normalized.encode()).hexdigest(), paragraphs)


def build_document_version(
    family: OfficialDocumentFamily,
    discovery: DiscoveredOfficialDocument,
    source: RawSourcePayload,
    extracted: ExtractedDocumentText,
    *,
    predecessor_version_id: str | None,
) -> OfficialDocumentVersion:
    family.validate_discovery(discovery)
    if source.authority is not SourceAuthority.OFFICIAL:
        raise ValueError("official document version requires OFFICIAL raw source authority")
    if source.source_id != discovery.source_id or source.url != discovery.document_url:
        raise ValueError("raw document source identity does not match discovered document")
    if source.retrieved_at < discovery.published_at:
        raise ValueError("document retrieval cannot precede discovered publication time")
    return OfficialDocumentVersion(
        family_id=family.family_id,
        source_id=family.source_id,
        document_type=family.document_type,
        institution=family.institution,
        currency=family.currency.upper(),
        discovery_id=discovery.discovery_id,
        item_id=discovery.item_id,
        document_url=discovery.document_url,
        published_at=discovery.published_at,
        available_at=source.available_at,
        source_record_id=source.record_id,
        source_payload_sha256=source.payload_sha256,
        text_sha256=extracted.text_sha256,
        text=extracted.text,
        predecessor_version_id=predecessor_version_id,
    )


def compare_document_versions(
    previous: OfficialDocumentVersion,
    current: OfficialDocumentVersion,
) -> OfficialDocumentDiff:
    if previous.family_id != current.family_id:
        raise ValueError("cannot compare official documents from different explicit families")
    if current.predecessor_version_id != previous.version_id:
        raise ValueError("current document predecessor does not match the compared previous version")
    previous_paragraphs = previous.paragraphs
    current_paragraphs = current.paragraphs
    matcher = SequenceMatcher(a=previous_paragraphs, b=current_paragraphs, autojunk=False)
    added: list[DocumentTextChange] = []
    removed: list[DocumentTextChange] = []
    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag in {"replace", "delete"}:
            removed.extend(DocumentTextChange.create("removed", index, previous_paragraphs[index]) for index in range(i1, i2))
        if tag in {"replace", "insert"}:
            added.extend(DocumentTextChange.create("added", index, current_paragraphs[index]) for index in range(j1, j2))
    return OfficialDocumentDiff(previous.family_id, previous.version_id, current.version_id, tuple(added), tuple(removed))


class _VisibleTextParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._excluded_depth = 0
        self.parts: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        del attrs
        normalized = tag.lower()
        if normalized in _EXCLUDED_TAGS:
            self._excluded_depth += 1
            return
        if self._excluded_depth == 0 and normalized in _BLOCK_TAGS:
            self.parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        normalized = tag.lower()
        if normalized in _EXCLUDED_TAGS:
            if self._excluded_depth > 0:
                self._excluded_depth -= 1
            return
        if self._excluded_depth == 0 and normalized in _BLOCK_TAGS:
            self.parts.append("\n")

    def handle_data(self, data: str) -> None:
        if self._excluded_depth == 0 and data:
            self.parts.append(data)


def _extract_html(body: bytes) -> str:
    text = _decode_utf8(body)
    upper = text.upper()
    if "<!DOCTYPE" in upper or "<!ENTITY" in upper:
        raise ValueError("official HTML document cannot contain DTD or entity declarations")
    parser = _VisibleTextParser()
    try:
        parser.feed(text)
        parser.close()
    except Exception as exc:
        raise ValueError("official HTML document could not be parsed") from exc
    return "".join(parser.parts)


def _decode_utf8(body: bytes) -> str:
    try:
        return body.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise ValueError("official document body must be valid UTF-8") from exc


def _normalize_visible_text(text: str) -> str:
    paragraphs: list[str] = []
    for line in text.splitlines():
        normalized = _WHITESPACE.sub(" ", line).strip()
        if normalized:
            paragraphs.append(normalized)
    return "\n".join(paragraphs)


def _require_sha256(value: str, name: str) -> None:
    if len(value) != 64:
        raise ValueError(f"{name} must be a SHA-256 hex digest")
    try:
        int(value, 16)
    except ValueError as exc:
        raise ValueError(f"{name} must be a SHA-256 hex digest") from exc
