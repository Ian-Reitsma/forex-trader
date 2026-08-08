from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from forex_trader.application.macro_ingestion import ProviderPollRunner
from forex_trader.infrastructure.official_document_repository import OfficialDocumentRepository
from forex_trader.infrastructure.source_evidence_repository import SourceEvidenceRepository
from forex_trader.ingestion.official_feeds import DiscoveredOfficialDocument
from forex_trader.ingestion.official_sources import OFFICIAL_MACRO_SOURCES, OfficialSourceClient
from forex_trader.intelligence.official_documents import (
    OfficialDocumentDiff,
    OfficialDocumentFamily,
    OfficialDocumentVersion,
    build_document_version,
    compare_document_versions,
    extract_official_document_text,
)


@dataclass(frozen=True, slots=True)
class OfficialDocumentEvidenceResult:
    version: OfficialDocumentVersion
    diff: OfficialDocumentDiff | None
    source_payload_inserted: bool
    version_inserted: bool


@dataclass(slots=True)
class OfficialDocumentEvidenceOrchestrator:
    source_repository: SourceEvidenceRepository
    document_repository: OfficialDocumentRepository
    poll_runner: ProviderPollRunner

    def ingest(
        self,
        family: OfficialDocumentFamily,
        discovery: DiscoveredOfficialDocument,
        client: OfficialSourceClient,
        *,
        retrieved_at: datetime,
    ) -> OfficialDocumentEvidenceResult:
        if retrieved_at.tzinfo is None:
            raise ValueError("official document retrieved_at must be timezone-aware")
        family.validate_discovery(discovery)
        if client.descriptor.source_id != family.source_id:
            raise ValueError("official document client source does not match explicit document family")
        canonical = OFFICIAL_MACRO_SOURCES.get(family.source_id)
        if canonical is None or client.descriptor != canonical:
            raise ValueError("official document client must use the canonical official source descriptor")
        if retrieved_at < discovery.published_at:
            raise ValueError("official document cannot be retrieved before its discovered publication time")

        source = self.poll_runner.run(
            family.source_id,
            observed_at=retrieved_at,
            operation=lambda: client.fetch(
                discovery.document_url,
                retrieved_at=retrieved_at,
                published_at=discovery.published_at,
                available_at=retrieved_at,
            ),
        )
        source_inserted = self.source_repository.save_payload(source)
        if self.source_repository.payload(source.record_id) != source:
            raise RuntimeError("official document raw payload was not durably retained")
        extracted = extract_official_document_text(source)

        equivalent = self.document_repository.equivalent(
            family_id=family.family_id,
            discovery_id=discovery.discovery_id,
            source_payload_sha256=source.payload_sha256,
            text_sha256=extracted.text_sha256,
        )
        if equivalent is not None:
            return OfficialDocumentEvidenceResult(equivalent, None, source_inserted, False)

        previous = self.document_repository.latest(family.family_id)
        version = build_document_version(
            family,
            discovery,
            source,
            extracted,
            predecessor_version_id=previous.version_id if previous is not None else None,
        )
        inserted = self.document_repository.append(version)
        if not inserted:
            stored = self.document_repository.get(version.version_id)
            if stored is None:
                raise RuntimeError("official document version was not durably retained")
            return OfficialDocumentEvidenceResult(stored, None, source_inserted, False)
        stored = self.document_repository.get(version.version_id)
        if stored != version:
            raise RuntimeError("official document version read-back did not match inserted evidence")
        diff = compare_document_versions(previous, version) if previous is not None else None
        return OfficialDocumentEvidenceResult(version, diff, source_inserted, True)
