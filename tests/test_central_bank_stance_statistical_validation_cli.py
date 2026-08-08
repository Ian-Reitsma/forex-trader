from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from scripts.validate_central_bank_stance_statistics import (
    FIXED_MAX_BASELINE_DELAY_SECONDS,
    _parse_as_of,
    validate_stance_statistics_from_files,
)
from forex_trader.infrastructure.official_document_repository import OfficialDocumentRepository
from forex_trader.intelligence.official_documents import OfficialDocumentVersion
from forex_trader.research.stance_outcomes import DEFAULT_STANCE_HORIZONS_MINUTES
from forex_trader.research.stance_statistical_validation import (
    PRIMARY_HORIZON_MINUTES,
    StanceStatisticalDisposition,
)


BASE = datetime(2020, 1, 1, 14, 0, tzinfo=UTC)
FAMILY = "fed_fomc_statistical_cli"
BASE_PRICE = Decimal("1.1000")


def version(
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
        document_url=f"https://www.federalreserve.gov/statistical-cli-{suffix}.htm",
        published_at=available_at - timedelta(seconds=1),
        available_at=available_at,
        source_record_id=hashlib.sha256(f"record-{suffix}".encode()).hexdigest(),
        source_payload_sha256=hashlib.sha256(f"payload-{suffix}".encode()).hexdigest(),
        text_sha256=hashlib.sha256(text.encode()).hexdigest(),
        text=text,
        predecessor_version_id=predecessor_version_id,
    )


def setup_files(tmp_path):  # type: ignore[no-untyped-def]
    database = tmp_path / "documents.db"
    archive = tmp_path / "candles.jsonl"
    repository = OfficialDocumentRepository(database)
    previous = version(
        index=0,
        text="The Committee met today.",
        available_at=BASE - timedelta(days=1),
        predecessor_version_id=None,
    )
    repository.append(previous)
    text = previous.text
    rows: list[dict[str, object]] = []
    aligned = {
        5: Decimal("3"),
        15: Decimal("4"),
        60: Decimal("6"),
        240: Decimal("5"),
    }
    for index in range(1, 25):
        text += "\nInflation remains elevated."
        available_at = BASE + timedelta(days=index)
        current = version(
            index=index,
            text=text,
            available_at=available_at,
            predecessor_version_id=previous.version_id,
        )
        repository.append(current)
        rows.append(
            {
                "instrument": "EUR_USD",
                "time": available_at.isoformat(),
                "open": str(BASE_PRICE),
                "high": "1.1002",
                "low": "1.0998",
                "close": str(BASE_PRICE),
            }
        )
        for horizon in DEFAULT_STANCE_HORIZONS_MINUTES:
            raw_bps = -aligned[horizon]
            price = BASE_PRICE * (Decimal("1") + raw_bps / Decimal("10000"))
            rows.append(
                {
                    "instrument": "EUR_USD",
                    "time": (available_at + timedelta(minutes=horizon)).isoformat(),
                    "open": str(price),
                    "high": str(price + Decimal("0.0002")),
                    "low": str(price - Decimal("0.0002")),
                    "close": str(price),
                }
            )
        previous = current
    archive.write_text("\n".join(json.dumps(row) for row in rows) + "\n", encoding="utf-8")
    return database, archive, BASE + timedelta(days=25)


def test_file_validator_uses_frozen_fixed_policy_and_returns_candidate(tmp_path) -> None:
    database, archive, as_of = setup_files(tmp_path)
    report = validate_stance_statistics_from_files(
        database,
        archive,
        family_id=FAMILY,
        instrument="eur_usd",
        as_of=as_of,
    )
    assert report.disposition is StanceStatisticalDisposition.INFORMATIONAL_SIGNAL_CANDIDATE
    assert report.directional_event_count == 24
    assert report.calibration_event_count == 16
    assert report.holdout_event_count == 8
    assert report.primary_horizon_minutes == PRIMARY_HORIZON_MINUTES == 60
    assert report.horizon_minutes == DEFAULT_STANCE_HORIZONS_MINUTES
    assert FIXED_MAX_BASELINE_DELAY_SECONDS == Decimal("300")
    assert report.research_only is True
    assert report.execution_authority is False


def test_file_validator_fails_closed_on_naive_cutoff_missing_family_and_instrument(tmp_path) -> None:
    database, archive, as_of = setup_files(tmp_path)
    with pytest.raises(ValueError, match="timezone-aware"):
        validate_stance_statistics_from_files(
            database,
            archive,
            family_id=FAMILY,
            instrument="EUR_USD",
            as_of=as_of.replace(tzinfo=None),
        )
    with pytest.raises(ValueError, match="requires at least two"):
        validate_stance_statistics_from_files(
            database,
            archive,
            family_id="missing_family",
            instrument="EUR_USD",
            as_of=as_of,
        )
    with pytest.raises(ValueError, match="no observations for USD_JPY"):
        validate_stance_statistics_from_files(
            database,
            archive,
            family_id=FAMILY,
            instrument="USD_JPY",
            as_of=as_of,
        )


def test_parse_as_of_requires_explicit_timezone() -> None:
    assert _parse_as_of("2026-08-08T12:00:00+00:00") == datetime(2026, 8, 8, 12, 0, tzinfo=UTC)
    with pytest.raises(ValueError, match="timezone-aware"):
        _parse_as_of("2026-08-08T12:00:00")
