from __future__ import annotations

import hashlib
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from forex_trader.domain.models import Candle
from forex_trader.infrastructure.official_document_repository import OfficialDocumentRepository
from forex_trader.intelligence.official_documents import OfficialDocumentVersion
from forex_trader.research.central_bank_stance import EvidenceDisposition, StanceDirection
from forex_trader.research.stance_outcomes import (
    STANCE_OUTCOME_PRICE_SEMANTICS,
    build_stance_outcome_dataset,
)


BASE = datetime(2026, 8, 8, 12, 0, tzinfo=UTC)
FAMILY = "fed_fomc_statement"


def version(
    *,
    suffix: str,
    text: str,
    available_at: datetime,
    predecessor_version_id: str | None,
    currency: str = "USD",
) -> OfficialDocumentVersion:
    return OfficialDocumentVersion(
        family_id=FAMILY,
        source_id="federal_reserve",
        document_type="monetary_policy_statement",
        institution="Federal Reserve",
        currency=currency,
        discovery_id=hashlib.sha256(f"discovery-{suffix}".encode()).hexdigest(),
        item_id=f"item-{suffix}",
        document_url=f"https://www.federalreserve.gov/statement-{suffix}.htm",
        published_at=available_at - timedelta(seconds=1),
        available_at=available_at,
        source_record_id=hashlib.sha256(f"record-{suffix}".encode()).hexdigest(),
        source_payload_sha256=hashlib.sha256(f"payload-{suffix}".encode()).hexdigest(),
        text_sha256=hashlib.sha256(text.encode()).hexdigest(),
        text=text,
        predecessor_version_id=predecessor_version_id,
    )


def candle(minutes: int, price: str, *, complete: bool = True) -> Candle:
    value = Decimal(price)
    return Candle(
        time=BASE + timedelta(minutes=minutes),
        open=value,
        high=value + Decimal("0.0005"),
        low=value - Decimal("0.0005"),
        close=value,
        complete=complete,
    )


def hawkish_versions(*, available_at: datetime = BASE) -> tuple[OfficialDocumentVersion, OfficialDocumentVersion]:
    first = version(
        suffix="first",
        text="Inflation has eased.",
        available_at=available_at - timedelta(days=40),
        predecessor_version_id=None,
    )
    second = version(
        suffix="second",
        text="Inflation remains elevated.",
        available_at=available_at,
        predecessor_version_id=first.version_id,
    )
    return first, second


def test_quote_currency_hawkish_stance_aligns_pair_decline_positive() -> None:
    versions = hawkish_versions()
    dataset = build_stance_outcome_dataset(
        versions,
        (candle(0, "1.1000"), candle(5, "1.0990"), candle(15, "1.0970")),
        instrument="EUR_USD",
        horizon_minutes=(5, 15),
    )

    assert dataset.events_considered == 1
    assert dataset.events_observed == 1
    assert dataset.events_excluded == 0
    assert dataset.policy_currency == "USD"
    assert dataset.price_semantics == STANCE_OUTCOME_PRICE_SEMANTICS
    assert len(dataset.outcomes) == 2
    assert all(item.stance_direction is StanceDirection.HAWKISH for item in dataset.outcomes)
    assert all(item.stance_aligned_return_bps is not None and item.stance_aligned_return_bps > 0 for item in dataset.outcomes)
    assert all(item.raw_return_bps < 0 for item in dataset.outcomes)
    assert dataset.summaries[0].stance_aligned_hit_rate == Decimal("1")


def test_base_currency_hawkish_stance_aligns_pair_rise_positive() -> None:
    first, second = hawkish_versions()
    prices = (
        Candle(BASE, Decimal("145.00"), Decimal("145.10"), Decimal("144.90"), Decimal("145.00")),
        Candle(BASE + timedelta(minutes=5), Decimal("145.20"), Decimal("145.30"), Decimal("145.10"), Decimal("145.20")),
    )
    dataset = build_stance_outcome_dataset(
        (second, first),
        reversed(prices),
        instrument="USD_JPY",
        horizon_minutes=(5,),
    )
    outcome = dataset.outcomes[0]
    assert outcome.raw_return_bps > 0
    assert outcome.stance_aligned_return_bps is not None
    assert outcome.stance_aligned_return_bps > 0


def test_dovish_quote_currency_stance_aligns_pair_rise_positive() -> None:
    first = version(
        suffix="first",
        text="Inflation remains elevated.",
        available_at=BASE - timedelta(days=40),
        predecessor_version_id=None,
    )
    second = version(
        suffix="second",
        text="Inflation has eased.",
        available_at=BASE,
        predecessor_version_id=first.version_id,
    )
    dataset = build_stance_outcome_dataset(
        (first, second),
        (candle(0, "1.1000"), candle(5, "1.1010")),
        instrument="EUR_USD",
        horizon_minutes=(5,),
    )
    outcome = dataset.outcomes[0]
    assert outcome.stance_direction is StanceDirection.DOVISH
    assert outcome.raw_return_bps > 0
    assert outcome.stance_aligned_return_bps is not None
    assert outcome.stance_aligned_return_bps > 0


def test_contradictory_stance_is_retained_without_directional_alignment() -> None:
    first = version(
        suffix="first",
        text="The Committee met today.",
        available_at=BASE - timedelta(days=40),
        predecessor_version_id=None,
    )
    second = version(
        suffix="second",
        text="Inflation remains elevated. Inflation has eased.",
        available_at=BASE,
        predecessor_version_id=first.version_id,
    )
    dataset = build_stance_outcome_dataset(
        (first, second),
        (candle(0, "1.1000"), candle(5, "1.1010")),
        instrument="EUR_USD",
        horizon_minutes=(5,),
    )
    outcome = dataset.outcomes[0]
    summary = dataset.summaries[0]
    assert outcome.stance_direction is StanceDirection.CONTRADICTORY
    assert outcome.stance_disposition is EvidenceDisposition.CONTRADICTORY
    assert outcome.stance_aligned_return_bps is None
    assert summary.directional_sample_size == 0
    assert summary.stance_aligned_hit_rate is None


def test_complete_horizon_panel_prevents_selective_horizon_denominators() -> None:
    versions = hawkish_versions()
    dataset = build_stance_outcome_dataset(
        versions,
        (candle(0, "1.1000"), candle(5, "1.0990")),
        instrument="EUR_USD",
        horizon_minutes=(5, 60),
    )
    assert dataset.events_considered == 1
    assert dataset.events_observed == 0
    assert dataset.events_excluded == 1
    assert dataset.outcomes == ()
    assert dataset.summaries == ()
    assert dataset.exclusions[0].reason == "missing_horizon:60"
    assert dataset.exclusions[0].stance_direction is StanceDirection.HAWKISH


def test_as_of_and_baseline_delay_fail_closed_without_dropping_denominator() -> None:
    versions = hawkish_versions(available_at=BASE + timedelta(minutes=2))
    delayed = (
        candle(10, "1.1000"),
        candle(15, "1.0990"),
    )
    dataset = build_stance_outcome_dataset(
        versions,
        delayed,
        instrument="EUR_USD",
        horizon_minutes=(5,),
        max_baseline_delay_seconds=Decimal("300"),
    )
    assert dataset.events_excluded == 1
    assert dataset.exclusions[0].reason.startswith("baseline_delay_exceeded:")

    on_time_versions = hawkish_versions()
    immature = build_stance_outcome_dataset(
        on_time_versions,
        (candle(0, "1.1000"), candle(5, "1.0990")),
        instrument="EUR_USD",
        horizon_minutes=(5, 15),
        as_of=BASE + timedelta(minutes=6),
    )
    assert immature.events_excluded == 1
    assert immature.exclusions[0].reason == "missing_horizon:15"


def test_dataset_identity_is_stable_under_input_order() -> None:
    first, second = hawkish_versions()
    candles = (candle(0, "1.1000"), candle(5, "1.0990"), candle(15, "1.0980"))
    first_dataset = build_stance_outcome_dataset(
        (first, second),
        candles,
        instrument="EUR_USD",
        horizon_minutes=(15, 5, 15),
    )
    second_dataset = build_stance_outcome_dataset(
        (second, first),
        reversed(candles),
        instrument="eur_usd",
        horizon_minutes=(5, 15),
    )
    assert first_dataset.dataset_id == second_dataset.dataset_id
    assert first_dataset.outcomes == second_dataset.outcomes


def test_outcome_builder_rejects_invalid_pair_duplicate_candles_and_lineage_drift() -> None:
    first, second = hawkish_versions()
    with pytest.raises(ValueError, match="policy currency must be a leg"):
        build_stance_outcome_dataset(
            (first, second),
            (candle(0, "1.1000"), candle(5, "1.0990")),
            instrument="EUR_GBP",
            horizon_minutes=(5,),
        )
    duplicate = candle(0, "1.1000")
    with pytest.raises(ValueError, match="duplicate timestamps"):
        build_stance_outcome_dataset(
            (first, second),
            (duplicate, duplicate, candle(5, "1.0990")),
            instrument="EUR_USD",
            horizon_minutes=(5,),
        )
    drifted = version(
        suffix="drifted",
        text="Inflation remains elevated.",
        available_at=BASE,
        predecessor_version_id=first.version_id,
        currency="EUR",
    )
    with pytest.raises(ValueError, match="lineage must preserve"):
        build_stance_outcome_dataset(
            (first, drifted),
            (candle(0, "1.1000"), candle(5, "1.0990")),
            instrument="EUR_USD",
            horizon_minutes=(5,),
        )


def test_repository_returns_family_versions_in_point_in_time_order(tmp_path) -> None:
    path = tmp_path / "documents.db"
    repository = OfficialDocumentRepository(path)
    first, second = hawkish_versions()
    assert repository.family_versions(FAMILY) == ()
    repository.append(first)
    repository.append(second)
    assert repository.family_versions(FAMILY) == (first, second)
    with pytest.raises(ValueError, match="family_id is required"):
        repository.family_versions(" ")
