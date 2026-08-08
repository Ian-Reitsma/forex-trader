from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from scripts.analyze_central_bank_stance_outcomes import (
    _parse_as_of,
    _parse_decimal,
    _parse_horizons,
    analyze_stance_outcomes,
)
from forex_trader.infrastructure.official_document_repository import OfficialDocumentRepository
from forex_trader.intelligence.official_documents import OfficialDocumentVersion
from forex_trader.research.central_bank_stance import StanceDirection


BASE = datetime(2026, 8, 8, 12, 0, tzinfo=UTC)
FAMILY = "fed_fomc_statement"


def version(
    *,
    suffix: str,
    text: str,
    available_at: datetime,
    predecessor_version_id: str | None,
) -> OfficialDocumentVersion:
    return OfficialDocumentVersion(
        family_id=FAMILY,
        source_id="federal_reserve",
        document_type="monetary_policy_statement",
        institution="Federal Reserve",
        currency="USD",
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


def write_archive(path) -> None:  # type: ignore[no-untyped-def]
    rows = [
        {"instrument": "EUR_USD", "time": BASE.isoformat(), "open": "1.1000", "high": "1.1005", "low": "1.0995", "close": "1.1000"},
        {"instrument": "EUR_USD", "time": (BASE + timedelta(minutes=5)).isoformat(), "open": "1.0990", "high": "1.0995", "low": "1.0985", "close": "1.0990"},
        {"instrument": "EUR_USD", "time": (BASE + timedelta(minutes=15)).isoformat(), "open": "1.0970", "high": "1.0975", "low": "1.0965", "close": "1.0970"},
    ]
    path.write_text("\n".join(json.dumps(row) for row in rows) + "\n", encoding="utf-8")


def setup_documents(path) -> None:  # type: ignore[no-untyped-def]
    repository = OfficialDocumentRepository(path)
    first = version(
        suffix="first",
        text="Inflation has eased.",
        available_at=BASE - timedelta(days=40),
        predecessor_version_id=None,
    )
    repository.append(first)
    repository.append(
        version(
            suffix="second",
            text="Inflation remains elevated.",
            available_at=BASE,
            predecessor_version_id=first.version_id,
        )
    )


def test_analyze_stance_outcomes_builds_reproducible_complete_panel(tmp_path) -> None:
    database = tmp_path / "documents.db"
    archive = tmp_path / "candles.jsonl"
    setup_documents(database)
    write_archive(archive)

    dataset = analyze_stance_outcomes(
        database,
        archive,
        family_id=FAMILY,
        instrument="eur_usd",
        horizon_minutes=(15, 5, 15),
        max_baseline_delay_seconds=Decimal("300"),
        as_of=BASE + timedelta(minutes=20),
    )
    assert dataset.family_id == FAMILY
    assert dataset.instrument == "EUR_USD"
    assert dataset.horizon_minutes == (5, 15)
    assert dataset.events_considered == 1
    assert dataset.events_observed == 1
    assert len(dataset.outcomes) == 2
    assert all(item.stance_direction is StanceDirection.HAWKISH for item in dataset.outcomes)
    assert all(item.stance_aligned_return_bps is not None and item.stance_aligned_return_bps > 0 for item in dataset.outcomes)
    assert len(dataset.dataset_id) == 64

    repeated = analyze_stance_outcomes(
        database,
        archive,
        family_id=FAMILY,
        instrument="EUR_USD",
        horizon_minutes=(5, 15),
        max_baseline_delay_seconds=Decimal("300"),
        as_of=BASE + timedelta(minutes=20),
    )
    assert repeated.dataset_id == dataset.dataset_id


def test_analyze_stance_outcomes_fails_closed_on_missing_family_or_instrument(tmp_path) -> None:
    database = tmp_path / "documents.db"
    archive = tmp_path / "candles.jsonl"
    setup_documents(database)
    write_archive(archive)

    with pytest.raises(ValueError, match="family_id is required"):
        analyze_stance_outcomes(database, archive, family_id=" ", instrument="EUR_USD")
    with pytest.raises(ValueError, match="requires at least two"):
        analyze_stance_outcomes(database, archive, family_id="ecb_statement", instrument="EUR_USD")
    with pytest.raises(ValueError, match="no observations for USD_JPY"):
        analyze_stance_outcomes(database, archive, family_id=FAMILY, instrument="USD_JPY")


def test_stance_outcome_cli_parsers_are_explicit_and_fail_closed() -> None:
    assert _parse_horizons("5, 15,60") == (5, 15, 60)
    assert _parse_as_of("2026-08-08T12:00:00+00:00") == BASE
    assert _parse_as_of(None) is None
    assert _parse_decimal("300.5", "delay") == Decimal("300.5")
    with pytest.raises(ValueError, match="horizon minutes are required"):
        _parse_horizons(" , ")
    with pytest.raises(ValueError, match="comma-separated integers"):
        _parse_horizons("5,nope")
    with pytest.raises(ValueError, match="timezone-aware"):
        _parse_as_of("2026-08-08T12:00:00")
    with pytest.raises(ValueError, match="must be a decimal"):
        _parse_decimal("not-a-number", "delay")
