from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from forex_trader.application.macro_ingestion import MacroIngestionOrchestrator, MacroReadinessEvaluator, ProviderPollRunner
from forex_trader.domain.context import DataQualitySnapshot, HealthState, ProviderHealth
from forex_trader.infrastructure.source_evidence_repository import SourceEvidenceRepository
from forex_trader.ingestion.official_sources import (
    EconomicEventMapping,
    HttpPayload,
    LicensedConsensusEvidence,
    OfficialReleaseEvidence,
    OfficialSourceClient,
    RawSourcePayload,
    SourceAuthority,
    SourceDescriptor,
    validate_and_calculate_release,
)
from forex_trader.intelligence.events import ConsensusSnapshot, ReleaseActual


NOW = datetime(2026, 8, 7, 14, 0, tzinfo=UTC)
SCHEDULED = NOW + timedelta(minutes=30)
OFFICIAL = SourceDescriptor("official-x", "Official X", SourceAuthority.OFFICIAL, frozenset({"official.example"}))
LICENSED = SourceDescriptor("licensed-x", "Licensed X", SourceAuthority.LICENSED, frozenset({"licensed.example"}))


def mapping() -> EconomicEventMapping:
    return EconomicEventMapping(
        "event-map",
        "inflation",
        "USD",
        LICENSED.source_id,
        OFFICIAL.source_id,
        Decimal("-1"),
        "percent_yoy",
        Decimal("0.9"),
    )


def raw(descriptor: SourceDescriptor, *, at: datetime = NOW, body: bytes = b"payload") -> RawSourcePayload:
    return RawSourcePayload.create(
        descriptor=descriptor,
        url=f"https://{next(iter(descriptor.allowed_hosts))}/release",
        body=body,
        content_type="application/json; charset=utf-8",
        retrieved_at=at,
        published_at=at,
        available_at=at,
    )


def consensus(*, indicator: str = "inflation", currency: str = "USD", scheduled: datetime = SCHEDULED) -> LicensedConsensusEvidence:
    source = raw(LICENSED)
    return LicensedConsensusEvidence(
        source,
        ConsensusSnapshot(indicator, currency, Decimal("2.8"), Decimal("2.7"), NOW, source.source_id),
        scheduled,
    )


def official(*, indicator: str = "inflation", currency: str = "USD", scheduled: datetime = SCHEDULED) -> OfficialReleaseEvidence:
    at = SCHEDULED + timedelta(seconds=1)
    source = raw(OFFICIAL, at=at)
    return OfficialReleaseEvidence(
        source,
        ReleaseActual(indicator, currency, Decimal("3.0"), Decimal("2.6"), at, source.source_id),
        scheduled,
    )


class Transport:
    def __init__(self, response: HttpPayload) -> None:
        self.response = response

    def get(self, url: str, *, timeout_seconds: float) -> HttpPayload:
        assert url.startswith("https://")
        assert timeout_seconds > 0
        return self.response


class Sink:
    def save_macro_observation(self, observation) -> None:  # type: ignore[no-untyped-def]
        del observation


class ConsensusProvider:
    source_id = LICENSED.source_id

    def fetch_consensus(self, event_mapping, *, scheduled_at, observed_at):  # type: ignore[no-untyped-def]
        del event_mapping, scheduled_at, observed_at
        return consensus()


class OfficialProvider:
    source_id = OFFICIAL.source_id

    def fetch_release(self, event_mapping, *, scheduled_at, observed_at):  # type: ignore[no-untyped-def]
        del event_mapping, scheduled_at, observed_at
        return official()


def test_source_descriptor_rejects_invalid_identity_hosts_and_non_https() -> None:
    with pytest.raises(ValueError, match="source_id"):
        SourceDescriptor("", "Publisher", SourceAuthority.OFFICIAL, frozenset({"example.com"}))
    with pytest.raises(ValueError, match="allowed_hosts"):
        SourceDescriptor("x", "Publisher", SourceAuthority.OFFICIAL, frozenset())
    with pytest.raises(ValueError, match="invalid source host"):
        SourceDescriptor("x", "Publisher", SourceAuthority.OFFICIAL, frozenset({"bad:443"}))
    assert OFFICIAL.permits("https://sub.official.example/release") is True
    assert OFFICIAL.permits("http://official.example/release") is False
    assert OFFICIAL.permits("not-a-url") is False


def test_raw_payload_rejects_naive_chronology_and_bad_digest() -> None:
    valid = raw(OFFICIAL)
    naive = NOW.replace(tzinfo=None)
    with pytest.raises(ValueError, match="retrieved_at"):
        RawSourcePayload(
            valid.source_id,
            valid.publisher,
            valid.authority,
            valid.url,
            valid.content_type,
            naive,
            NOW,
            NOW,
            valid.payload_sha256,
            valid.body,
        )
    with pytest.raises(ValueError, match="available_at cannot precede"):
        RawSourcePayload.create(
            descriptor=OFFICIAL,
            url="https://official.example/x",
            body=b"x",
            content_type="text/plain",
            retrieved_at=NOW,
            published_at=NOW,
            available_at=NOW - timedelta(seconds=1),
        )
    with pytest.raises(ValueError, match="retrieved_at cannot precede"):
        RawSourcePayload.create(
            descriptor=OFFICIAL,
            url="https://official.example/x",
            body=b"x",
            content_type="text/plain",
            retrieved_at=NOW,
            published_at=NOW,
            available_at=NOW + timedelta(seconds=1),
        )
    with pytest.raises(ValueError, match="SHA-256"):
        RawSourcePayload(
            valid.source_id,
            valid.publisher,
            valid.authority,
            valid.url,
            valid.content_type,
            valid.retrieved_at,
            valid.published_at,
            valid.available_at,
            "bad",
            valid.body,
        )


def test_official_client_rejects_wrong_authority_config_and_http_failures_and_accepts_success() -> None:
    ok_response = HttpPayload(200, {"content-type": "text/plain; charset=utf-8"}, b"ok", "https://official.example/x")
    with pytest.raises(ValueError, match="OFFICIAL"):
        OfficialSourceClient(LICENSED, Transport(ok_response))
    with pytest.raises(ValueError, match="positive"):
        OfficialSourceClient(OFFICIAL, Transport(ok_response), maximum_payload_bytes=0)
    with pytest.raises(ValueError, match="positive"):
        OfficialSourceClient(OFFICIAL, Transport(ok_response), timeout_seconds=0)

    bad_status = OfficialSourceClient(
        OFFICIAL,
        Transport(HttpPayload(503, {}, b"down", "https://official.example/x")),
    )
    with pytest.raises(RuntimeError, match="HTTP 503"):
        bad_status.fetch("https://official.example/x", retrieved_at=NOW, published_at=NOW)

    client = OfficialSourceClient(OFFICIAL, Transport(ok_response))
    payload = client.fetch("https://official.example/x", retrieved_at=NOW, published_at=NOW)
    assert payload.body == b"ok"
    assert payload.content_type == "text/plain"
    with pytest.raises(ValueError, match="not permitted"):
        client.fetch("https://evil.example/x", retrieved_at=NOW, published_at=NOW)


def test_event_mapping_rejects_bad_identity_currency_direction_and_importance() -> None:
    with pytest.raises(ValueError, match="identity"):
        EconomicEventMapping("", "inflation", "USD", "c", "o", Decimal("-1"), "pct")
    with pytest.raises(ValueError, match="three-letter"):
        EconomicEventMapping("x", "inflation", "US", "c", "o", Decimal("-1"), "pct")
    with pytest.raises(ValueError, match="directionality"):
        EconomicEventMapping("x", "inflation", "USD", "c", "o", Decimal("0"), "pct")
    with pytest.raises(ValueError, match="importance"):
        EconomicEventMapping("x", "inflation", "USD", "c", "o", Decimal("-1"), "pct", Decimal("0"))
    assert mapping().metadata.currency == "USD"


def test_evidence_contracts_reject_naive_schedule_source_mismatch_and_early_actual() -> None:
    c = consensus()
    o = official()
    with pytest.raises(ValueError, match="scheduled_at"):
        LicensedConsensusEvidence(c.source, c.snapshot, SCHEDULED.replace(tzinfo=None))
    bad_snapshot = ConsensusSnapshot("inflation", "USD", Decimal("2.8"), Decimal("2.7"), NOW, "other")
    with pytest.raises(ValueError, match="source does not match"):
        LicensedConsensusEvidence(c.source, bad_snapshot, SCHEDULED)

    with pytest.raises(ValueError, match="scheduled_at"):
        OfficialReleaseEvidence(o.source, o.actual, SCHEDULED.replace(tzinfo=None))
    early_source = raw(OFFICIAL)
    early_actual = ReleaseActual("inflation", "USD", Decimal("3"), Decimal("2.7"), NOW, early_source.source_id)
    with pytest.raises(ValueError, match="before the scheduled"):
        OfficialReleaseEvidence(early_source, early_actual, SCHEDULED)
    mismatched_actual = ReleaseActual("inflation", "USD", Decimal("3"), Decimal("2.7"), SCHEDULED + timedelta(seconds=1), "other")
    with pytest.raises(ValueError, match="source does not match"):
        OfficialReleaseEvidence(o.source, mismatched_actual, SCHEDULED)


def test_release_join_rejects_source_schedule_indicator_and_currency_mismatches() -> None:
    c = consensus()
    o = official()
    wrong_source_mapping = EconomicEventMapping("x", "inflation", "USD", "other", OFFICIAL.source_id, Decimal("-1"), "pct")
    with pytest.raises(ValueError, match="consensus source"):
        validate_and_calculate_release(wrong_source_mapping, c, o)

    with pytest.raises(ValueError, match="scheduled timestamps"):
        validate_and_calculate_release(mapping(), c, official(scheduled=SCHEDULED - timedelta(minutes=1)))
    with pytest.raises(ValueError, match="indicator"):
        validate_and_calculate_release(mapping(), c, official(indicator="labor"))
    with pytest.raises(ValueError, match="currency"):
        validate_and_calculate_release(mapping(), c, official(currency="EUR"))


def test_repository_validates_query_time_age_and_missing_provider(tmp_path) -> None:
    repository = SourceEvidenceRepository(tmp_path / "source.db")
    with pytest.raises(ValueError, match="timezone-aware"):
        repository.payloads_as_of("x", NOW.replace(tzinfo=None))
    with pytest.raises(ValueError, match="timezone-aware"):
        repository.latest_health("x", as_of=NOW.replace(tzinfo=None), maximum_age_seconds=Decimal("1"))
    with pytest.raises(ValueError, match="cannot be negative"):
        repository.latest_health("x", as_of=NOW, maximum_age_seconds=Decimal("-1"))
    missing = repository.latest_health("x", as_of=NOW, maximum_age_seconds=Decimal("10"))
    assert missing.state is HealthState.UNAVAILABLE
    assert missing.heartbeat_age_seconds == Decimal("11")


def test_poll_success_and_macro_orchestration_timestamp_provider_guards(tmp_path) -> None:
    repository = SourceEvidenceRepository(tmp_path / "source.db")
    runner = ProviderPollRunner(repository)
    assert runner.run("x", observed_at=NOW, operation=lambda: 7) == 7
    assert repository.latest_health("x", as_of=NOW, maximum_age_seconds=Decimal("1")).state is HealthState.HEALTHY
    with pytest.raises(ValueError, match="timezone-aware"):
        runner.run("x", observed_at=NOW.replace(tzinfo=None), operation=lambda: 1)

    orchestrator = MacroIngestionOrchestrator(repository, runner, Sink())
    with pytest.raises(ValueError, match="timezone-aware"):
        orchestrator.fetch_and_ingest_release(
            mapping(),
            consensus_provider=ConsensusProvider(),
            official_provider=OfficialProvider(),
            scheduled_at=SCHEDULED.replace(tzinfo=None),
            consensus_observed_at=NOW,
            official_observed_at=SCHEDULED,
        )
    with pytest.raises(ValueError, match="cannot be polled before"):
        orchestrator.fetch_and_ingest_release(
            mapping(),
            consensus_provider=ConsensusProvider(),
            official_provider=OfficialProvider(),
            scheduled_at=SCHEDULED,
            consensus_observed_at=NOW,
            official_observed_at=SCHEDULED - timedelta(seconds=1),
        )

    bad_consensus = ConsensusProvider()
    bad_consensus.source_id = "other"  # type: ignore[misc]
    with pytest.raises(ValueError, match="consensus provider"):
        orchestrator.fetch_and_ingest_release(
            mapping(),
            consensus_provider=bad_consensus,
            official_provider=OfficialProvider(),
            scheduled_at=SCHEDULED,
            consensus_observed_at=NOW,
            official_observed_at=SCHEDULED,
        )

    bad_official = OfficialProvider()
    bad_official.source_id = "other"  # type: ignore[misc]
    with pytest.raises(ValueError, match="official provider"):
        orchestrator.fetch_and_ingest_release(
            mapping(),
            consensus_provider=ConsensusProvider(),
            official_provider=bad_official,
            scheduled_at=SCHEDULED,
            consensus_observed_at=NOW,
            official_observed_at=SCHEDULED,
        )


def test_macro_readiness_validates_configuration_and_timestamps(tmp_path) -> None:
    repository = SourceEvidenceRepository(tmp_path / "source.db")
    with pytest.raises(ValueError, match="cannot be negative"):
        MacroReadinessEvaluator(repository, maximum_poll_age_seconds=Decimal("-1"))
    evaluator = MacroReadinessEvaluator(repository)
    with pytest.raises(ValueError, match="timezone-aware"):
        evaluator.evaluate(
            mapping(),
            scheduled_at=SCHEDULED.replace(tzinfo=None),
            as_of=NOW,
            data_quality=DataQualitySnapshot(observed_at=NOW),
        )
