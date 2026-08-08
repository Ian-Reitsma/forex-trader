from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from forex_trader.application.macro_ingestion import ProviderPollRunner
from forex_trader.infrastructure.source_evidence_repository import SourceEvidenceRepository
from forex_trader.ingestion.official_feeds import FeedDiscoveryResult, OfficialFeedDiscovery


@dataclass(slots=True)
class OfficialDocumentDiscoveryOrchestrator:
    source_repository: SourceEvidenceRepository
    poll_runner: ProviderPollRunner

    def poll(
        self,
        discovery: OfficialFeedDiscovery,
        *,
        observed_at: datetime,
    ) -> FeedDiscoveryResult:
        if observed_at.tzinfo is None:
            raise ValueError("observed_at must be timezone-aware")
        result = self.poll_runner.run(
            discovery.definition.source_id,
            observed_at=observed_at,
            operation=lambda: discovery.fetch(retrieved_at=observed_at),
        )
        self.source_repository.save_payload(result.feed_payload)
        persisted = self.source_repository.payload(result.feed_payload.record_id)
        if persisted != result.feed_payload:
            raise RuntimeError("official feed payload was not durably retained")
        return result
