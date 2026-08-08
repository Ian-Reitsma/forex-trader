from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from forex_trader.application.macro_ingestion import (
    MacroIngestionOrchestrator,
    MacroReadinessEvaluator,
    MacroReadinessPhase,
    ProviderPollRunner,
    ProviderRateLimitedError,
)
from forex_trader.domain.context import DataQualitySnapshot, HealthState, ProviderHealth
from forex_trader.domain.macro_history import MacroObservation
from forex_trader.infrastructure.source_evidence_repository import SourceEvidenceRepository
from forex_trader.ingestion.official_sources import (
    OFFICIAL_MACRO_SOURCES,
    EconomicEventMapping,
    HttpPayload,
    LicensedConsensusEvidence,
    OfficialReleaseEvidence,
    OfficialSourceClient,
    RawSourcePayload,
    SourceAuthority,
    SourceDescriptor,
)
from forex_trader.intelligence.events import ConsensusSnapshot, ReleaseActual


NOW = datetime(2026, 8, 7, 14, 0, tzinfo=UTC)
SCHEDULED = NOW + timedelta(minutes=30)
LICENSED = SourceDescriptor(
    "licensed-calendar",
    "Licensed Calendar Vendor",
    SourceAuthority.LICENSED,
    frozenset({"calendar.vendor.example"}),
)


def event_mapping() -> EconomicEventMapping:
    return EconomicEventMapping(
        mapping_id="us-cpi-headline-yoy",
        indicator="inflation",
        currency="USD",
        consensus_source_id=LICENSED.source_id,
        official_source_id="bls",
        directionality=Decimal("-1"),
        unit="percent_yoy",
        importance=Decimal("0.95"),
    )


def licensed_payload(*, retrieved_at: datetime = NOW) -> RawSourcePayload:
    return RawSourcePayload.create(
        descriptor=LICENSED,
        url="https://calendar.vendor.example/api/events/us-cpi",
        body=b'{"consensus":"2.8","previous":"2.7"}',
        content_type="application/json",
        retrieved_at=retrieved_at,
        published_at=NOW - timedelta(minutes=5),
        available_at=NOW - timedelta(minutes=5),
    )


def consensus_evidence() -> LicensedConsensusEvidence:
    source = licensed_payload()
    return LicensedConsensusEvidence(
        source,
        ConsensusSnapshot(
            indicator="inflation",
            currency="USD",
            consensus=Decimal("2.8"),
            previous_known=Decimal("2.7"),
            available_at=NOW,
            source=source.source_id,
        ),
        SCHEDULED,
    )


def official_evidence() -> OfficialReleaseEvidence:
    available = SCHEDULED + timedelta(seconds=2)
    source = RawSourcePayload.create(
        descriptor=OFFICIAL_MACRO_SOURCES["bls"],
        url="https://www.bls.gov/news.release/cpi.nr0.htm",
        body=b"official cpi release",
        content_type="text/plain",
        retrieved_at=available + timedelta(seconds=1),
        published_at=available,
        available_at=available,
    )
    return OfficialReleaseEvidence(
        source,
        ReleaseActual(
            indicator="inflation",
            currency="USD",
            actual=Decimal("3.0"),
            revised_previous=Decimal("2.6"),
            available_at=available,
            source=source.source_id,
        ),
        SCHEDULED,
    )


class Sink:
    def __init__(self) -> None:
        self.rows: dict[str, MacroObservation] = {}

    def save_macro_observation(self, observation: MacroObservation) -> None:
        self.rows[str(observation.observation_id)] = observation


class ConsensusProvider:
    source_id = LICENSED.source_id

    def __init__(self, evidence: LicensedConsensusEvidence) -> None:
        self.evidence = evidence
        self.calls = 0

    def fetch_consensus(
        self,
        mapping: EconomicEventMapping,
        *,
        scheduled_at: datetime,
        observed_at: datetime,
    ) -> LicensedConsensusEvidence:
        self.calls += 1
        assert mapping.mapping_id == "us-cpi-headline-yoy"
        assert scheduled_at == SCHEDULED
        assert observed_at <= scheduled_at
        return self.evidence


class OfficialProvider:
    source_id = "bls"

    def __init__(self, evidence: OfficialReleaseEvidence) -> None:
        self.evidence = evidence
        self.calls = 0

    def fetch_release(
        self,
        mapping: EconomicEventMapping,
        *,
        scheduled_at: datetime,
        observed_at: datetime,
    ) -> OfficialReleaseEvidence:
        self.calls += 1
        assert mapping.mapping_id == "us-cpi-headline-yoy"
        assert scheduled_at == SCHEDULED
        assert observed_at >= scheduled_at
        return self.evidence


class FakeTransport:
    def __init__(self, response: HttpPayload) -> None:
        self.response = response
        self.urls: list[str] = []

    def get(self, url: str, *, timeout_seconds: float) -> HttpPayload:
        assert timeout_seconds > 0
        self.urls.append(url)
        return self.response


def test_source_descriptor_and_official_client_fail_closed_on_host_escape_and_size() -> None:
    descriptor = OFFICIAL_MACRO_SOURCES["bls"]
    assert descriptor.permits("https://www.bls.gov/news.release/cpi.nr0.htm") is True
    assert descriptor.permits("http://www.bls.gov/news.release/cpi.nr0.htm") is False
    assert descriptor.permits("https://bls.gov.evil.example/cpi") is False

    escaped = FakeTransport(HttpPayload(200, {"content-type": "text/plain"}, b"x", "https://evil.example/x"))
    client = OfficialSourceClient(descriptor, escaped)
    with pytest.raises(RuntimeError, match="escaped"):
        client.fetch(
            "https://www.bls.gov/x",
            retrieved_at=NOW,
            published_at=NOW,
        )

    oversized = FakeTransport(HttpPayload(200, {}, b"abcd", "https://www.bls.gov/x"))
    small_client = OfficialSourceClient(descriptor, oversized, maximum_payload_bytes=3)
    with pytest.raises(RuntimeError, match="maximum size"):
        small_client.fetch(
            "https://www.bls.gov/x",
            retrieved_at=NOW,
            published_at=NOW,
        )


def test_raw_source_payload_binds_body_and_retrieval_provenance() -> None:
    first = licensed_payload()
    second = licensed_payload(retrieved_at=NOW + timedelta(seconds=1))
    assert first.payload_sha256 == second.payload_sha256
    assert first.record_id != second.record_id

    with pytest.raises(ValueError, match="does not match body"):
        RawSourcePayload(
            source_id=first.source_id,
            publisher=first.publisher,
            authority=first.authority,
            url=first.url,
            content_type=first.content_type,
            retrieved_at=first.retrieved_at,
            published_at=first.published_at,
            available_at=first.available_at,
            payload_sha256="0" * 64,
            body=first.body,
        )


def test_source_repository_round_trips_payload_and_point_in_time_health(tmp_path) -> None:
    repository = SourceEvidenceRepository(tmp_path / "sources.db")
    payload = licensed_payload()
    assert repository.save_payload(payload) is True
    assert repository.save_payload(payload) is False
    assert repository.payload(payload.record_id) == payload
    assert repository.payloads_as_of(payload.source_id, NOW - timedelta(minutes=10)) == ()
    assert repository.payloads_as_of(payload.source_id, NOW) == (payload,)

    repository.save_health(ProviderHealth(payload.source_id, HealthState.HEALTHY, NOW, detail="fresh"))
    fresh = repository.latest_health(payload.source_id, as_of=NOW + timedelta(seconds=5), maximum_age_seconds=Decimal("10"))
    assert fresh.state is HealthState.HEALTHY
    assert fresh.heartbeat_age_seconds == Decimal("5.0")

    stale = repository.latest_health(payload.source_id, as_of=NOW + timedelta(seconds=20), maximum_age_seconds=Decimal("10"))
    assert stale.state is HealthState.UNAVAILABLE
    assert stale.heartbeat_age_seconds == Decimal("20.0")


def test_consensus_and_official_authority_and_schedule_rules_are_enforced() -> None:
    consensus = consensus_evidence()
    official = official_evidence()
    assert consensus.source.authority is SourceAuthority.LICENSED
    assert official.source.authority is SourceAuthority.OFFICIAL

    with pytest.raises(ValueError, match="LICENSED"):
        LicensedConsensusEvidence(
            official.source,
            consensus.snapshot,
            SCHEDULED,
        )
    with pytest.raises(ValueError, match="scheduled release"):
        LicensedConsensusEvidence(
            consensus.source,
            ConsensusSnapshot(
                "inflation",
                "USD",
                Decimal("2.8"),
                Decimal("2.7"),
                SCHEDULED + timedelta(seconds=1),
                consensus.source.source_id,
            ),
            SCHEDULED,
        )


def test_orchestrator_persists_raw_evidence_and_produces_deterministic_macro_observation(tmp_path) -> None:
    repository = SourceEvidenceRepository(tmp_path / "sources.db")
    sink = Sink()
    runner = ProviderPollRunner(repository)
    orchestrator = MacroIngestionOrchestrator(repository, runner, sink)
    consensus = consensus_evidence()
    official = official_evidence()
    consensus_provider = ConsensusProvider(consensus)
    official_provider = OfficialProvider(official)

    first = orchestrator.fetch_and_ingest_release(
        event_mapping(),
        consensus_provider=consensus_provider,
        official_provider=official_provider,
        scheduled_at=SCHEDULED,
        consensus_observed_at=NOW,
        official_observed_at=SCHEDULED + timedelta(seconds=3),
    )
    second = orchestrator.ingest_release(event_mapping(), consensus=consensus, official=official)

    assert first.observation.observation_id == second.observation.observation_id
    assert first.observation.actual == Decimal("3.0")
    assert first.observation.forecast == Decimal("2.8")
    assert first.observation.previous == Decimal("2.6")
    assert first.surprise.raw_surprise == Decimal("-0.2")
    assert len(sink.rows) == 1
    assert repository.payload(first.consensus_record_id) == consensus.source
    assert repository.payload(first.official_record_id) == official.source
    assert consensus_provider.calls == official_provider.calls == 1
    assert first.consensus_payload_inserted is True
    assert second.consensus_payload_inserted is False


def test_orchestrator_refuses_time_travel_and_provider_identity_mismatch(tmp_path) -> None:
    repository = SourceEvidenceRepository(tmp_path / "sources.db")
    orchestrator = MacroIngestionOrchestrator(repository, ProviderPollRunner(repository), Sink())
    consensus_provider = ConsensusProvider(consensus_evidence())
    official_provider = OfficialProvider(official_evidence())

    with pytest.raises(ValueError, match="no later"):
        orchestrator.fetch_and_ingest_release(
            event_mapping(),
            consensus_provider=consensus_provider,
            official_provider=official_provider,
            scheduled_at=SCHEDULED,
            consensus_observed_at=SCHEDULED + timedelta(seconds=1),
            official_observed_at=SCHEDULED + timedelta(seconds=2),
        )

    wrong_mapping = EconomicEventMapping(
        "wrong",
        "inflation",
        "USD",
        "other-calendar",
        "bls",
        Decimal("-1"),
        "percent_yoy",
    )
    with pytest.raises(ValueError, match="consensus provider"):
        orchestrator.fetch_and_ingest_release(
            wrong_mapping,
            consensus_provider=consensus_provider,
            official_provider=official_provider,
            scheduled_at=SCHEDULED,
            consensus_observed_at=NOW,
            official_observed_at=SCHEDULED + timedelta(seconds=2),
        )


def test_provider_poll_runner_records_rate_limit_and_errors(tmp_path) -> None:
    repository = SourceEvidenceRepository(tmp_path / "health.db")
    runner = ProviderPollRunner(repository)

    with pytest.raises(ProviderRateLimitedError):
        runner.run(
            "licensed-calendar",
            observed_at=NOW,
            operation=lambda: (_ for _ in ()).throw(ProviderRateLimitedError("429")),
        )
    limited = repository.latest_health(
        "licensed-calendar",
        as_of=NOW,
        maximum_age_seconds=Decimal("60"),
    )
    assert limited.state is HealthState.DEGRADED
    assert limited.rate_limited is True

    with pytest.raises(ValueError):
        runner.run(
            "bls",
            observed_at=NOW,
            operation=lambda: (_ for _ in ()).throw(ValueError("bad payload")),
        )
    broken = repository.latest_health("bls", as_of=NOW, maximum_age_seconds=Decimal("60"))
    assert broken.state is HealthState.UNAVAILABLE
    assert "ValueError" in broken.detail


def test_macro_readiness_requires_consensus_pre_release_and_both_sources_post_release(tmp_path) -> None:
    repository = SourceEvidenceRepository(tmp_path / "health.db")
    repository.save_health(ProviderHealth(LICENSED.source_id, HealthState.HEALTHY, NOW))
    evaluator = MacroReadinessEvaluator(repository, maximum_poll_age_seconds=Decimal("3600"))

    pre_time = NOW + timedelta(minutes=5)
    pre = evaluator.evaluate(
        event_mapping(),
        scheduled_at=SCHEDULED,
        as_of=pre_time,
        data_quality=DataQualitySnapshot(observed_at=pre_time),
    )
    assert pre.phase is MacroReadinessPhase.PRE_RELEASE
    assert pre.required_source_ids == (LICENSED.source_id,)
    assert pre.trading_readiness.ready is True

    post_time = SCHEDULED + timedelta(seconds=5)
    missing = evaluator.evaluate(
        event_mapping(),
        scheduled_at=SCHEDULED,
        as_of=post_time,
        data_quality=DataQualitySnapshot(observed_at=post_time),
    )
    assert missing.phase is MacroReadinessPhase.POST_RELEASE
    assert missing.required_source_ids == (LICENSED.source_id, "bls")
    assert missing.trading_readiness.ready is False
    assert any(reason.startswith("PROVIDER_UNAVAILABLE:bls") for reason in missing.trading_readiness.reasons)

    repository.save_health(ProviderHealth("bls", HealthState.HEALTHY, post_time))
    ready = evaluator.evaluate(
        event_mapping(),
        scheduled_at=SCHEDULED,
        as_of=post_time,
        data_quality=DataQualitySnapshot(observed_at=post_time),
    )
    assert ready.trading_readiness.ready is True


def test_macro_readiness_fails_closed_when_required_source_is_rate_limited(tmp_path) -> None:
    repository = SourceEvidenceRepository(tmp_path / "health.db")
    repository.save_health(
        ProviderHealth(
            LICENSED.source_id,
            HealthState.DEGRADED,
            NOW,
            rate_limited=True,
            detail="429",
        )
    )
    evaluator = MacroReadinessEvaluator(repository, maximum_poll_age_seconds=Decimal("3600"))
    result = evaluator.evaluate(
        event_mapping(),
        scheduled_at=SCHEDULED,
        as_of=NOW + timedelta(minutes=1),
        data_quality=DataQualitySnapshot(observed_at=NOW + timedelta(minutes=1)),
    )
    assert result.trading_readiness.ready is False
    assert "PROVIDER_RATE_LIMITED:licensed-calendar" in result.trading_readiness.reasons
