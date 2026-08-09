from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from forex_trader.intelligence.events import ConsensusSnapshot, ReleaseActual, ReleaseMetadata
from forex_trader.research.release_surprise_history import PointInTimeReleaseSurpriseAssembler

BASE = datetime(2026, 1, 9, 13, 30, tzinfo=UTC)
META = ReleaseMetadata("CPI YoY", "USD", Decimal("-1"), "%", "NSA")


def _consensus(value: str, *, hours_before: int = 1, seconds_before: int = 0, source: str = "vendor") -> ConsensusSnapshot:
    return ConsensusSnapshot(
        indicator="CPI YoY",
        currency="USD",
        consensus=Decimal(value),
        previous_known=Decimal("3.0"),
        available_at=BASE - timedelta(hours=hours_before, seconds=seconds_before),
        source=source,
    )


def _actual(value: str, *, when: datetime = BASE, previous: str = "3.0", source: str = "bls") -> ReleaseActual:
    return ReleaseActual(
        indicator="CPI YoY",
        currency="USD",
        actual=Decimal(value),
        revised_previous=Decimal(previous),
        available_at=when,
        source=source,
    )


def test_latest_strictly_pre_release_consensus_wins() -> None:
    early = _consensus("2.9", hours_before=4, source="early")
    latest = _consensus("2.8", hours_before=0, seconds_before=30, source="latest")
    same_timestamp = ConsensusSnapshot("CPI YoY", "USD", Decimal("2.7"), Decimal("3.0"), BASE, "ambiguous")
    post = ConsensusSnapshot("CPI YoY", "USD", Decimal("2.6"), Decimal("3.0"), BASE + timedelta(seconds=1), "future")

    report = PointInTimeReleaseSurpriseAssembler(
        (META,),
        (early, latest, same_timestamp, post),
        (_actual("2.6"),),
    ).assemble(require_complete=True)

    assert len(report.records) == 1
    record = report.records[0]
    assert record.consensus.source == "latest"
    assert record.consensus.consensus == Decimal("2.8")
    assert record.consensus_age == timedelta(seconds=30)
    # CPI directionality is -1: lower-than-consensus inflation is positive for USD in
    # this synthetic metadata example.
    assert record.surprise.raw_surprise == Decimal("0.2")


def test_future_release_cannot_change_earlier_normalization() -> None:
    first_time = BASE
    second_time = BASE + timedelta(days=28)
    future_time = BASE + timedelta(days=56)
    consensus = (
        _consensus("3.0", hours_before=1),
        ConsensusSnapshot("CPI YoY", "USD", Decimal("2.8"), Decimal("2.9"), second_time - timedelta(hours=1), "vendor"),
        ConsensusSnapshot("CPI YoY", "USD", Decimal("2.7"), Decimal("2.8"), future_time - timedelta(hours=1), "vendor"),
    )
    first_two_actuals = (
        _actual("2.9", when=first_time, previous="3.0"),
        _actual("2.6", when=second_time, previous="2.9"),
    )
    with_future = (*first_two_actuals, _actual("5.0", when=future_time, previous="2.6"))

    first_report = PointInTimeReleaseSurpriseAssembler((META,), consensus, first_two_actuals).assemble()
    future_report = PointInTimeReleaseSurpriseAssembler((META,), consensus, with_future).assemble()

    assert len(first_report.records) == 2
    assert len(future_report.records) == 3
    assert [item.surprise for item in first_report.records] == [
        item.surprise for item in future_report.records[:2]
    ]
    assert first_report.records[0].prior_same_indicator_samples == 0
    assert first_report.records[1].prior_same_indicator_samples == 1


def test_as_of_excludes_future_actuals_and_consensus() -> None:
    future_time = BASE + timedelta(days=28)
    future_consensus = ConsensusSnapshot(
        "CPI YoY",
        "USD",
        Decimal("2.8"),
        Decimal("2.9"),
        future_time - timedelta(hours=1),
        "vendor",
    )
    assembler = PointInTimeReleaseSurpriseAssembler(
        (META,),
        (_consensus("3.0"), future_consensus),
        (_actual("2.9"), _actual("2.6", when=future_time)),
    )

    report = assembler.assemble(as_of=BASE + timedelta(hours=1), require_complete=True)
    assert len(report.records) == 1
    assert report.records[0].actual.available_at == BASE


def test_stale_or_missing_consensus_is_explicitly_unmatched() -> None:
    stale = _consensus("2.9", hours_before=48)
    report = PointInTimeReleaseSurpriseAssembler(
        (META,),
        (stale,),
        (_actual("2.8"),),
        maximum_consensus_age=timedelta(hours=24),
    ).assemble()

    assert report.records == ()
    assert len(report.unmatched_actuals) == 1
    assert "stale" in report.unmatched_actuals[0].reason

    with pytest.raises(ValueError, match="incomplete"):
        PointInTimeReleaseSurpriseAssembler(
            (META,),
            (),
            (_actual("2.8"),),
        ).assemble(require_complete=True)


def test_missing_metadata_fails_closed_when_required() -> None:
    assembler = PointInTimeReleaseSurpriseAssembler((), (_consensus("2.9"),), (_actual("2.8"),))
    report = assembler.assemble()
    assert report.records == ()
    assert report.unmatched_actuals[0].reason == "missing release metadata"
    with pytest.raises(ValueError, match="missing release metadata"):
        assembler.assemble(require_complete=True)


def test_macro_observation_preserves_consensus_actual_revision_and_lineage() -> None:
    report = PointInTimeReleaseSurpriseAssembler(
        (META,),
        (_consensus("2.9", source="consensus-vendor"),),
        (_actual("2.7", previous="2.95", source="official-actual"),),
    ).assemble(require_complete=True)

    record = report.records[0]
    observation = record.to_macro_observation()
    assert observation.currency == "USD"
    assert observation.category == "CPI YoY"
    assert observation.actual == Decimal("2.7")
    assert observation.forecast == Decimal("2.9")
    assert observation.previous == Decimal("2.95")
    assert observation.available_at == BASE
    assert observation.higher_is_positive is False
    assert observation.source == "actual=official-actual|consensus=consensus-vendor"
    assert report.macro_observations() == (observation,)


def test_duplicate_metadata_and_naive_as_of_are_rejected() -> None:
    with pytest.raises(ValueError, match="duplicate"):
        PointInTimeReleaseSurpriseAssembler((META, META), (), ())
    with pytest.raises(ValueError, match="timezone-aware"):
        PointInTimeReleaseSurpriseAssembler((META,), (), ()).assemble(as_of=datetime(2026, 1, 1))
    with pytest.raises(ValueError, match="positive"):
        PointInTimeReleaseSurpriseAssembler((META,), (), (), maximum_consensus_age=timedelta(0))
