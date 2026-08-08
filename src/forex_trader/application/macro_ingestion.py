from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from enum import StrEnum
from typing import Callable, Protocol, TypeVar
from uuid import NAMESPACE_URL, uuid5

from forex_trader.domain.context import DataQualitySnapshot, HealthState, ProviderHealth, ReadinessPolicy, TradingReadiness
from forex_trader.domain.macro_history import MacroObservation
from forex_trader.infrastructure.source_evidence_repository import SourceEvidenceRepository
from forex_trader.ingestion.official_sources import (
    EconomicEventMapping,
    LicensedConsensusEvidence,
    OfficialReleaseEvidence,
    validate_and_calculate_release,
)
from forex_trader.intelligence.events import ReleaseSurprise


class MacroObservationSink(Protocol):
    def save_macro_observation(self, observation: MacroObservation) -> None: ...


class LicensedConsensusProvider(Protocol):
    source_id: str

    def fetch_consensus(
        self,
        mapping: EconomicEventMapping,
        *,
        scheduled_at: datetime,
        observed_at: datetime,
    ) -> LicensedConsensusEvidence: ...


class OfficialReleaseProvider(Protocol):
    source_id: str

    def fetch_release(
        self,
        mapping: EconomicEventMapping,
        *,
        scheduled_at: datetime,
        observed_at: datetime,
    ) -> OfficialReleaseEvidence: ...


class ProviderRateLimitedError(RuntimeError):
    pass


T = TypeVar("T")


@dataclass(frozen=True, slots=True)
class ProviderPollRunner:
    repository: SourceEvidenceRepository

    def run(self, provider: str, *, observed_at: datetime, operation: Callable[[], T]) -> T:
        if observed_at.tzinfo is None:
            raise ValueError("provider poll observed_at must be timezone-aware")
        try:
            result = operation()
        except ProviderRateLimitedError as exc:
            self.repository.save_health(
                ProviderHealth(
                    provider,
                    HealthState.DEGRADED,
                    observed_at,
                    rate_limited=True,
                    detail=str(exc) or "provider rate limited",
                )
            )
            raise
        except Exception as exc:
            self.repository.save_health(
                ProviderHealth(
                    provider,
                    HealthState.UNAVAILABLE,
                    observed_at,
                    detail=f"{type(exc).__name__}: {exc}",
                )
            )
            raise
        self.repository.save_health(ProviderHealth(provider, HealthState.HEALTHY, observed_at, detail="poll succeeded"))
        return result


@dataclass(frozen=True, slots=True)
class MacroIngestionResult:
    observation: MacroObservation
    surprise: ReleaseSurprise
    consensus_record_id: str
    official_record_id: str
    consensus_payload_inserted: bool
    official_payload_inserted: bool


@dataclass(slots=True)
class MacroIngestionOrchestrator:
    source_repository: SourceEvidenceRepository
    poll_runner: ProviderPollRunner
    observation_sink: MacroObservationSink

    def fetch_and_ingest_release(
        self,
        mapping: EconomicEventMapping,
        *,
        consensus_provider: LicensedConsensusProvider,
        official_provider: OfficialReleaseProvider,
        scheduled_at: datetime,
        consensus_observed_at: datetime,
        official_observed_at: datetime,
        historical_raw_surprises: tuple[Decimal, ...] = (),
    ) -> MacroIngestionResult:
        if scheduled_at.tzinfo is None or consensus_observed_at.tzinfo is None or official_observed_at.tzinfo is None:
            raise ValueError("macro ingestion timestamps must be timezone-aware")
        if consensus_observed_at > scheduled_at:
            raise ValueError("consensus must be polled no later than the scheduled release")
        if official_observed_at < scheduled_at:
            raise ValueError("official actual cannot be polled before the scheduled release")
        if consensus_provider.source_id != mapping.consensus_source_id:
            raise ValueError("consensus provider source_id does not match event mapping")
        if official_provider.source_id != mapping.official_source_id:
            raise ValueError("official provider source_id does not match event mapping")

        consensus = self.poll_runner.run(
            mapping.consensus_source_id,
            observed_at=consensus_observed_at,
            operation=lambda: consensus_provider.fetch_consensus(
                mapping,
                scheduled_at=scheduled_at,
                observed_at=consensus_observed_at,
            ),
        )
        official = self.poll_runner.run(
            mapping.official_source_id,
            observed_at=official_observed_at,
            operation=lambda: official_provider.fetch_release(
                mapping,
                scheduled_at=scheduled_at,
                observed_at=official_observed_at,
            ),
        )
        return self.ingest_release(
            mapping,
            consensus=consensus,
            official=official,
            historical_raw_surprises=historical_raw_surprises,
        )

    def ingest_release(
        self,
        mapping: EconomicEventMapping,
        *,
        consensus: LicensedConsensusEvidence,
        official: OfficialReleaseEvidence,
        historical_raw_surprises: tuple[Decimal, ...] = (),
    ) -> MacroIngestionResult:
        surprise = validate_and_calculate_release(
            mapping,
            consensus,
            official,
            historical_raw_surprises=historical_raw_surprises,
        )
        consensus_inserted = self.source_repository.save_payload(consensus.source)
        official_inserted = self.source_repository.save_payload(official.source)
        if self.source_repository.payload(consensus.source.record_id) != consensus.source:
            raise RuntimeError("licensed consensus raw evidence was not durably retained")
        if self.source_repository.payload(official.source.record_id) != official.source:
            raise RuntimeError("official release raw evidence was not durably retained")

        identity = ":".join(
            (
                "forex-trader-macro-release",
                mapping.mapping_id,
                consensus.source.record_id,
                official.source.record_id,
            )
        )
        observation = MacroObservation.release(
            currency=mapping.currency,
            category=mapping.indicator,
            actual=official.actual.actual,
            forecast=consensus.snapshot.consensus,
            previous=official.actual.revised_previous,
            higher_is_positive=mapping.directionality > 0,
            importance=mapping.importance,
            available_at=official.actual.available_at,
            source=official.source.source_id,
            observation_id=uuid5(NAMESPACE_URL, identity),
        )
        self.observation_sink.save_macro_observation(observation)
        return MacroIngestionResult(
            observation,
            surprise,
            consensus.source.record_id,
            official.source.record_id,
            consensus_inserted,
            official_inserted,
        )


class MacroReadinessPhase(StrEnum):
    PRE_RELEASE = "pre_release"
    POST_RELEASE = "post_release"


@dataclass(frozen=True, slots=True)
class MacroReadinessResult:
    phase: MacroReadinessPhase
    required_source_ids: tuple[str, ...]
    provider_health: tuple[ProviderHealth, ...]
    trading_readiness: TradingReadiness


@dataclass(frozen=True, slots=True)
class MacroReadinessEvaluator:
    source_repository: SourceEvidenceRepository
    readiness_policy: ReadinessPolicy = ReadinessPolicy()
    maximum_poll_age_seconds: Decimal = Decimal("300")

    def __post_init__(self) -> None:
        if self.maximum_poll_age_seconds < 0:
            raise ValueError("maximum_poll_age_seconds cannot be negative")

    def evaluate(
        self,
        mapping: EconomicEventMapping,
        *,
        scheduled_at: datetime,
        as_of: datetime,
        data_quality: DataQualitySnapshot,
    ) -> MacroReadinessResult:
        if scheduled_at.tzinfo is None or as_of.tzinfo is None:
            raise ValueError("macro readiness timestamps must be timezone-aware")
        phase = MacroReadinessPhase.PRE_RELEASE if as_of < scheduled_at else MacroReadinessPhase.POST_RELEASE
        required = (
            (mapping.consensus_source_id,)
            if phase is MacroReadinessPhase.PRE_RELEASE
            else (mapping.consensus_source_id, mapping.official_source_id)
        )
        health = tuple(
            self.source_repository.latest_health(
                source_id,
                as_of=as_of,
                maximum_age_seconds=self.maximum_poll_age_seconds,
            )
            for source_id in required
        )
        base = self.readiness_policy.evaluate(
            data_quality,
            health,
            require_calendar=False,
            require_fundamentals=False,
            require_flow=False,
        )
        rate_limited = tuple(item.provider for item in health if item.rate_limited)
        if not rate_limited:
            readiness = base
        else:
            reasons = base.reasons + tuple(f"PROVIDER_RATE_LIMITED:{item}" for item in rate_limited)
            readiness = TradingReadiness(False, reasons, tuple(sorted(set(base.degraded_sources + rate_limited))))
        return MacroReadinessResult(phase, required, health, readiness)
