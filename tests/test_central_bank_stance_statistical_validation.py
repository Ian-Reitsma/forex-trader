from __future__ import annotations

import hashlib
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from forex_trader.domain.models import Candle
from forex_trader.intelligence.official_documents import OfficialDocumentVersion
from forex_trader.research.stance_outcomes import (
    DEFAULT_STANCE_HORIZONS_MINUTES,
    build_stance_outcome_dataset,
)
from forex_trader.research.stance_statistical_validation import (
    BOOTSTRAP_ITERATIONS,
    FAMILYWISE_CONFIDENCE,
    FIXED_MAX_BASELINE_DELAY_SECONDS,
    MIN_CALIBRATION_EVENTS,
    MIN_DIRECTIONAL_EVENTS,
    MIN_HOLDOUT_EVENTS,
    PRIMARY_HORIZON_MINUTES,
    SIMULTANEOUS_METHOD,
    SPLIT_POLICY,
    StanceStatisticalDisposition,
    validate_stance_outcome_statistics,
)


BASE = datetime(2020, 1, 1, 14, 0, tzinfo=UTC)
FAMILY = "fed_fomc_statistical_fixture"
BASE_PRICE = Decimal("1.1000")


def _version(
    *,
    index: int,
    text: str,
    available_at: datetime,
    predecessor_version_id: str | None,
) -> OfficialDocumentVersion:
    suffix = str(index)
    return OfficialDocumentVersion(
        family_id=FAMILY,
        source_id="federal_reserve",
        document_type="monetary_policy_statement",
        institution="Federal Reserve",
        currency="USD",
        discovery_id=hashlib.sha256(f"discovery-{suffix}".encode()).hexdigest(),
        item_id=f"item-{suffix}",
        document_url=f"https://www.federalreserve.gov/statistical-{suffix}.htm",
        published_at=available_at - timedelta(seconds=1),
        available_at=available_at,
        source_record_id=hashlib.sha256(f"record-{suffix}".encode()).hexdigest(),
        source_payload_sha256=hashlib.sha256(f"payload-{suffix}".encode()).hexdigest(),
        text_sha256=hashlib.sha256(text.encode()).hexdigest(),
        text=text,
        predecessor_version_id=predecessor_version_id,
    )


def _candle(time: datetime, price: Decimal) -> Candle:
    return Candle(
        time=time,
        open=price,
        high=price + Decimal("0.0002"),
        low=price - Decimal("0.0002"),
        close=price,
        complete=True,
    )


def _price_for_aligned_bps(aligned_bps: Decimal) -> Decimal:
    # USD is quote currency in EUR_USD; hawkish USD alignment is positive when the pair falls.
    raw_bps = -aligned_bps
    return BASE_PRICE * (Decimal("1") + raw_bps / Decimal("10000"))


def build_fixture_dataset(
    directional_returns: tuple[tuple[Decimal, Decimal, Decimal, Decimal], ...],
    *,
    neutral_events: int = 0,
    excluded_events: int = 0,
    frozen: bool = True,
    max_baseline_delay_seconds: Decimal = FIXED_MAX_BASELINE_DELAY_SECONDS,
):  # type: ignore[no-untyped-def]
    versions: list[OfficialDocumentVersion] = []
    candles: list[Candle] = []
    previous = _version(
        index=0,
        text="The Committee met today.",
        available_at=BASE - timedelta(days=1),
        predecessor_version_id=None,
    )
    versions.append(previous)
    current_text = previous.text
    event_index = 0
    for returns in directional_returns:
        event_index += 1
        current_text = current_text + "\nInflation remains elevated."
        available_at = BASE + timedelta(days=event_index)
        current = _version(
            index=event_index,
            text=current_text,
            available_at=available_at,
            predecessor_version_id=previous.version_id,
        )
        versions.append(current)
        candles.append(_candle(available_at, BASE_PRICE))
        for horizon, aligned in zip(DEFAULT_STANCE_HORIZONS_MINUTES, returns, strict=True):
            candles.append(_candle(available_at + timedelta(minutes=horizon), _price_for_aligned_bps(aligned)))
        previous = current

    for neutral_index in range(neutral_events):
        event_index += 1
        current_text = current_text + f"\nOperational note {neutral_index}."
        available_at = BASE + timedelta(days=event_index)
        current = _version(
            index=event_index,
            text=current_text,
            available_at=available_at,
            predecessor_version_id=previous.version_id,
        )
        versions.append(current)
        candles.append(_candle(available_at, BASE_PRICE))
        for horizon in DEFAULT_STANCE_HORIZONS_MINUTES:
            candles.append(_candle(available_at + timedelta(minutes=horizon), BASE_PRICE))
        previous = current

    for _ in range(excluded_events):
        event_index += 1
        current_text = current_text + "\nInflation remains elevated."
        current = _version(
            index=event_index,
            text=current_text,
            available_at=BASE + timedelta(days=event_index),
            predecessor_version_id=previous.version_id,
        )
        versions.append(current)
        previous = current

    cutoff = BASE + timedelta(days=event_index + 1) if frozen else None
    return build_stance_outcome_dataset(
        versions,
        candles,
        instrument="EUR_USD",
        horizon_minutes=DEFAULT_STANCE_HORIZONS_MINUTES,
        max_baseline_delay_seconds=max_baseline_delay_seconds,
        as_of=cutoff,
    )


def constant_returns(
    count: int,
    values: tuple[str, str, str, str] = ("3", "4", "6", "5"),
) -> tuple[tuple[Decimal, Decimal, Decimal, Decimal], ...]:
    row = tuple(Decimal(value) for value in values)
    assert len(row) == 4
    return tuple(row for _ in range(count))  # type: ignore[return-value]


def test_positive_untouched_primary_holdout_becomes_informational_candidate() -> None:
    dataset = build_fixture_dataset(constant_returns(30), neutral_events=2)
    report = validate_stance_outcome_statistics(dataset)

    assert report.disposition is StanceStatisticalDisposition.INFORMATIONAL_SIGNAL_CANDIDATE
    assert report.research_only is True
    assert report.execution_authority is False
    assert report.primary_horizon_minutes == PRIMARY_HORIZON_MINUTES == 60
    assert report.horizon_minutes == DEFAULT_STANCE_HORIZONS_MINUTES
    assert report.familywise_confidence == FAMILYWISE_CONFIDENCE
    assert report.bootstrap_iterations == BOOTSTRAP_ITERATIONS
    assert report.simultaneous_method == SIMULTANEOUS_METHOD
    assert report.split_policy == SPLIT_POLICY
    assert report.source_as_of == dataset.as_of.isoformat()  # type: ignore[union-attr]
    assert report.source_max_baseline_delay_seconds == FIXED_MAX_BASELINE_DELAY_SECONDS
    assert report.directional_event_count == 30
    assert report.nondirectional_event_count == 2
    assert report.calibration_event_count == 20
    assert report.holdout_event_count == 10
    assert report.calibration is not None
    assert report.holdout is not None
    assert report.calibration.event_count == 20
    assert report.holdout.event_count == 10
    assert set(report.calibration.event_ids).isdisjoint(report.holdout.event_ids)
    assert report.calibration.last_document_available_at < report.holdout.first_document_available_at
    primary = next(item for item in report.holdout.bands if item.horizon_minutes == 60)
    assert primary.mean_stance_aligned_return_bps == Decimal("6")
    assert primary.lower_simultaneous_mean_bps == Decimal("6")
    assert primary.upper_simultaneous_mean_bps == Decimal("6")
    assert primary.stance_aligned_hit_rate == Decimal("1")
    assert "not executable expectancy" in report.reasons[0]


def test_predeclared_60_minute_primary_rejects_despite_strong_other_horizons() -> None:
    dataset = build_fixture_dataset(constant_returns(30, ("12", "9", "-6", "8")))
    report = validate_stance_outcome_statistics(dataset)
    assert report.disposition is StanceStatisticalDisposition.REJECTED
    assert report.holdout is not None
    five = next(item for item in report.holdout.bands if item.horizon_minutes == 5)
    primary = next(item for item in report.holdout.bands if item.horizon_minutes == 60)
    assert five.lower_simultaneous_mean_bps > 0
    assert primary.upper_simultaneous_mean_bps < 0
    assert any("60-minute" in reason for reason in report.reasons)


def test_interval_crossing_zero_is_insufficient_not_optimized_to_best_horizon() -> None:
    rows = list(constant_returns(30, ("10", "8", "1", "6")))
    for index in range(20, 30):
        five, fifteen, _, twoforty = rows[index]
        rows[index] = (five, fifteen, Decimal("8") if index % 2 else Decimal("-8"), twoforty)
    report = validate_stance_outcome_statistics(build_fixture_dataset(tuple(rows)))
    assert report.disposition is StanceStatisticalDisposition.INSUFFICIENT_EVIDENCE
    assert report.holdout is not None
    primary = next(item for item in report.holdout.bands if item.horizon_minutes == 60)
    assert primary.lower_simultaneous_mean_bps <= 0 <= primary.upper_simultaneous_mean_bps
    assert any("includes zero" in reason for reason in report.reasons)


def test_minimum_sample_requirements_are_fixed_and_fail_closed() -> None:
    report = validate_stance_outcome_statistics(build_fixture_dataset(constant_returns(23)))
    assert report.disposition is StanceStatisticalDisposition.INSUFFICIENT_EVIDENCE
    assert report.directional_event_count == 23
    assert report.calibration is None
    assert report.holdout is None
    assert report.minimum_directional_events == MIN_DIRECTIONAL_EVENTS == 24
    assert report.minimum_calibration_events == MIN_CALIBRATION_EVENTS == 16
    assert report.minimum_holdout_events == MIN_HOLDOUT_EVENTS == 8
    assert any("below fixed minimums" in reason for reason in report.reasons)


def test_low_observation_coverage_blocks_candidate_even_with_enough_directional_events() -> None:
    dataset = build_fixture_dataset(constant_returns(30), excluded_events=10)
    report = validate_stance_outcome_statistics(dataset)
    assert dataset.events_considered == 40
    assert dataset.events_observed == 30
    assert report.observed_event_fraction == Decimal("0.75")
    assert report.calibration is not None
    assert report.holdout is not None
    assert report.disposition is StanceStatisticalDisposition.INSUFFICIENT_EVIDENCE
    assert any("observed event fraction" in reason for reason in report.reasons)


def test_joint_bootstrap_is_deterministic_and_uses_one_width_across_family() -> None:
    rows = tuple(
        (
            Decimal("2") + Decimal(index % 3),
            Decimal("3") + Decimal(index % 4),
            Decimal("5") + Decimal(index % 5),
            Decimal("4") + Decimal(index % 2),
        )
        for index in range(30)
    )
    dataset = build_fixture_dataset(rows)
    first = validate_stance_outcome_statistics(dataset)
    second = validate_stance_outcome_statistics(dataset)
    assert first.report_id == second.report_id
    assert first.calibration == second.calibration
    assert first.holdout == second.holdout
    assert first.holdout is not None
    widths = {
        item.upper_simultaneous_mean_bps - item.mean_stance_aligned_return_bps
        for item in first.holdout.bands
    }
    assert widths == {first.holdout.simultaneous_critical_width_bps}


def test_source_dataset_horizon_family_cannot_be_narrowed_for_validation() -> None:
    previous = _version(
        index=900,
        text="The Committee met today.",
        available_at=BASE - timedelta(days=1),
        predecessor_version_id=None,
    )
    current = _version(
        index=901,
        text="The Committee met today.\nInflation remains elevated.",
        available_at=BASE,
        predecessor_version_id=previous.version_id,
    )
    narrow_dataset = build_stance_outcome_dataset(
        (previous, current),
        (_candle(BASE, BASE_PRICE), _candle(BASE + timedelta(minutes=60), _price_for_aligned_bps(Decimal("5")))),
        instrument="EUR_USD",
        horizon_minutes=(60,),
        max_baseline_delay_seconds=FIXED_MAX_BASELINE_DELAY_SECONDS,
        as_of=BASE + timedelta(hours=2),
    )
    with pytest.raises(ValueError, match="fixed 5/15/60/240"):
        validate_stance_outcome_statistics(narrow_dataset)


def test_direct_validator_rejects_unfrozen_or_tuned_preprocessing() -> None:
    unfrozen = build_fixture_dataset(constant_returns(24), frozen=False)
    assert unfrozen.as_of is None
    with pytest.raises(ValueError, match="frozen as_of"):
        validate_stance_outcome_statistics(unfrozen)

    tuned_delay = build_fixture_dataset(
        constant_returns(24),
        max_baseline_delay_seconds=Decimal("600"),
    )
    assert tuned_delay.max_baseline_delay_seconds == Decimal("600")
    with pytest.raises(ValueError, match="fixed 300-second"):
        validate_stance_outcome_statistics(tuned_delay)


def test_statistical_report_identity_detects_tampering() -> None:
    report = validate_stance_outcome_statistics(build_fixture_dataset(constant_returns(30)))
    with pytest.raises(ValueError, match="report ID"):
        replace(report, reasons=("tampered",))
