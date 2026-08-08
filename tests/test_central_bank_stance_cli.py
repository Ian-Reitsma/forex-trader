from __future__ import annotations

import hashlib
from datetime import UTC, datetime, timedelta

import pytest

from scripts.analyze_central_bank_stance import analyze_stance
from forex_trader.infrastructure.official_document_repository import OfficialDocumentRepository
from forex_trader.intelligence.official_documents import OfficialDocumentVersion
from forex_trader.research.central_bank_stance import EvidenceDisposition, StanceDirection


BASE = datetime(2026, 8, 8, 4, 0, tzinfo=UTC)
FAMILY = "fed_fomc_statement"


def version(
    *,
    suffix: str,
    text: str,
    available_at: datetime,
    predecessor_version_id: str | None,
    family_id: str = FAMILY,
) -> OfficialDocumentVersion:
    text_hash = hashlib.sha256(text.encode()).hexdigest()
    return OfficialDocumentVersion(
        family_id=family_id,
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
        text_sha256=text_hash,
        text=text,
        predecessor_version_id=predecessor_version_id,
    )


def test_analyze_stance_uses_latest_persisted_predecessor_pair(tmp_path) -> None:
    path = tmp_path / "documents.db"
    repository = OfficialDocumentRepository(path)
    first = version(
        suffix="first",
        text="Inflation remains elevated.",
        available_at=BASE,
        predecessor_version_id=None,
    )
    repository.append(first)
    second = version(
        suffix="second",
        text="Inflation has moved closer to the Committee's objective.",
        available_at=BASE + timedelta(minutes=1),
        predecessor_version_id=first.version_id,
    )
    repository.append(second)

    evidence = analyze_stance(path, family_id=FAMILY)
    assert evidence.previous_version_id == first.version_id
    assert evidence.current_version_id == second.version_id
    assert evidence.direction is StanceDirection.DOVISH
    assert evidence.disposition is EvidenceDisposition.SUPPORTED
    assert {item.change_side for item in evidence.spans} == {"added", "removed"}
    assert evidence.execution_authority is False


def test_analyze_stance_can_pin_current_version_and_fails_closed_on_invalid_requests(tmp_path) -> None:
    path = tmp_path / "documents.db"
    repository = OfficialDocumentRepository(path)
    first = version(
        suffix="first",
        text="Inflation remains elevated.",
        available_at=BASE,
        predecessor_version_id=None,
    )
    repository.append(first)
    second = version(
        suffix="second",
        text="Inflation has eased.",
        available_at=BASE + timedelta(minutes=1),
        predecessor_version_id=first.version_id,
    )
    repository.append(second)

    pinned = analyze_stance(path, family_id=FAMILY, current_version_id=second.version_id)
    assert pinned.current_version_id == second.version_id

    with pytest.raises(ValueError, match="family_id is required"):
        analyze_stance(path, family_id=" ")
    with pytest.raises(ValueError, match="was not found"):
        analyze_stance(path, family_id=FAMILY, current_version_id="0" * 64)
    with pytest.raises(ValueError, match="no predecessor"):
        analyze_stance(path, family_id=FAMILY, current_version_id=first.version_id)
    with pytest.raises(ValueError, match="no official document version"):
        analyze_stance(path, family_id="ecb_statement")


def test_analyze_stance_rejects_current_version_from_another_family(tmp_path) -> None:
    path = tmp_path / "documents.db"
    repository = OfficialDocumentRepository(path)
    other = version(
        suffix="other",
        text="Inflation has eased.",
        available_at=BASE,
        predecessor_version_id=None,
        family_id="other-family",
    )
    repository.append(other)
    with pytest.raises(ValueError, match="does not belong"):
        analyze_stance(path, family_id=FAMILY, current_version_id=other.version_id)
