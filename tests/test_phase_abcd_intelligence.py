from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from forex_trader.intelligence.events import (
    CentralBankExtraction,
    ConsensusSnapshot,
    EvidenceSpan,
    NewsDocument,
    ReleaseActual,
    ReleaseMetadata,
    calculate_release_surprise,
    cluster_news,
)

NOW = datetime(2026, 8, 7, 12, 0, tzinfo=UTC)


def test_release_surprise_uses_pre_release_consensus_revision_and_history() -> None:
    meta = ReleaseMetadata("CPI", "USD", Decimal("1"), unit="pct")
    consensus = ConsensusSnapshot("CPI", "USD", Decimal("3.0"), Decimal("2.8"), NOW, "calendar")
    actual = ReleaseActual("CPI", "USD", Decimal("3.4"), Decimal("2.9"), NOW + timedelta(seconds=1), "official")
    result = calculate_release_surprise(
        meta,
        consensus,
        actual,
        historical_raw_surprises=(Decimal("0.1"), Decimal("0.2"), Decimal("0.3")),
    )
    assert result.raw_surprise == Decimal("0.4")
    assert result.normalized_surprise > 0
    assert result.revision_effect > 0
    assert result.combined_signal > result.normalized_surprise

    inverse = calculate_release_surprise(
        ReleaseMetadata("Unemployment", "USD", Decimal("-1")),
        ConsensusSnapshot("Unemployment", "USD", Decimal("4.0"), Decimal("3.9"), NOW, "calendar"),
        ReleaseActual("Unemployment", "USD", Decimal("4.2"), Decimal("3.9"), NOW + timedelta(seconds=1), "official"),
    )
    assert inverse.combined_signal < 0


def test_release_contracts_fail_on_future_consensus_and_mismatch() -> None:
    with pytest.raises(ValueError):
        ReleaseMetadata("CPI", "USD", Decimal("0"))
    meta = ReleaseMetadata("CPI", "USD", Decimal("1"))
    with pytest.raises(ValueError):
        calculate_release_surprise(
            meta,
            ConsensusSnapshot("CPI", "USD", Decimal("3"), Decimal("3"), NOW + timedelta(seconds=2), "x"),
            ReleaseActual("CPI", "USD", Decimal("3.1"), Decimal("3"), NOW, "x"),
        )
    with pytest.raises(ValueError):
        calculate_release_surprise(
            meta,
            ConsensusSnapshot("PCE", "USD", Decimal("3"), Decimal("3"), NOW, "x"),
            ReleaseActual("PCE", "USD", Decimal("3.1"), Decimal("3"), NOW + timedelta(seconds=1), "x"),
        )


def test_news_documents_cluster_syndication_without_double_counting() -> None:
    first = NewsDocument(
        "a",
        "Fed holds rates steady",
        "body one",
        "wire-a",
        NOW,
        NOW + timedelta(seconds=2),
        Decimal("0.8"),
    )
    second = NewsDocument(
        "b",
        "  Fed holds rates steady  ",
        "body two",
        "wire-b",
        NOW + timedelta(seconds=1),
        NOW + timedelta(seconds=3),
        Decimal("0.9"),
    )
    third = NewsDocument(
        "c",
        "ECB changes guidance",
        "different",
        "official",
        NOW,
        NOW + timedelta(seconds=1),
        Decimal("1"),
    )
    clusters = cluster_news((second, third, first))
    assert len(clusters) == 2
    fed = next(item for item in clusters if item.source_count == 2)
    assert fed.authoritative_source == "wire-b"
    assert fed.earliest_publication == NOW


def test_news_document_validation() -> None:
    with pytest.raises(ValueError):
        NewsDocument("x", "h", "b", "s", datetime(2026, 1, 1), NOW)
    with pytest.raises(ValueError):
        NewsDocument("x", "h", "b", "s", NOW, NOW - timedelta(seconds=1))
    with pytest.raises(ValueError):
        NewsDocument("x", "h", "b", "s", NOW, NOW, Decimal("2"))


def test_evidence_spans_and_central_bank_schema_are_traceable() -> None:
    text = "Inflation remains elevated but growth has slowed."
    span = EvidenceSpan.from_text(text, 0, 26)
    assert len(span.text_hash) == 64
    extraction = CentralBankExtraction(
        document_id="fed-1",
        institution="Federal Reserve",
        currency="USD",
        event_type="statement",
        stance_delta={"inflation": Decimal("0.4"), "growth": Decimal("-0.2")},
        caveats=("conditional",),
        evidence_spans=(span,),
        confidence=Decimal("0.8"),
        disposition="supported",
        prompt_version="p1",
        model_version="m1",
    )
    assert extraction.stance_delta["inflation"] > 0
    with pytest.raises(ValueError):
        EvidenceSpan.from_text(text, 4, 4)
    with pytest.raises(ValueError):
        CentralBankExtraction("x", "Fed", "USD", "speech", {"policy": Decimal("2")}, (), (), Decimal("1"), "supported", "p", "m")
    with pytest.raises(ValueError):
        CentralBankExtraction("x", "Fed", "USD", "speech", {}, (), (), Decimal("1.1"), "supported", "p", "m")
    with pytest.raises(ValueError):
        CentralBankExtraction("x", "Fed", "USD", "speech", {}, (), (), Decimal("1"), "unknown", "p", "m")
