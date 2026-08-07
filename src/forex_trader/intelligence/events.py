from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from statistics import median
from typing import Iterable


@dataclass(frozen=True, slots=True)
class ReleaseMetadata:
    indicator: str
    currency: str
    directionality: Decimal
    unit: str = ""
    seasonal_adjustment: str = ""

    def __post_init__(self) -> None:
        if self.directionality not in {Decimal("-1"), Decimal("1")}:
            raise ValueError("directionality must be -1 or 1")


@dataclass(frozen=True, slots=True)
class ConsensusSnapshot:
    indicator: str
    currency: str
    consensus: Decimal
    previous_known: Decimal
    available_at: datetime
    source: str

    def __post_init__(self) -> None:
        if self.available_at.tzinfo is None:
            raise ValueError("consensus available_at must be timezone-aware")


@dataclass(frozen=True, slots=True)
class ReleaseActual:
    indicator: str
    currency: str
    actual: Decimal
    revised_previous: Decimal
    available_at: datetime
    source: str

    def __post_init__(self) -> None:
        if self.available_at.tzinfo is None:
            raise ValueError("release available_at must be timezone-aware")


@dataclass(frozen=True, slots=True)
class ReleaseSurprise:
    raw_surprise: Decimal
    normalized_surprise: Decimal
    revision_effect: Decimal
    combined_signal: Decimal
    scale: Decimal


def calculate_release_surprise(
    metadata: ReleaseMetadata,
    consensus: ConsensusSnapshot,
    actual: ReleaseActual,
    *,
    historical_raw_surprises: Iterable[Decimal] = (),
) -> ReleaseSurprise:
    if metadata.indicator != consensus.indicator or metadata.indicator != actual.indicator:
        raise ValueError("indicator mismatch")
    if metadata.currency.upper() != consensus.currency.upper() or metadata.currency.upper() != actual.currency.upper():
        raise ValueError("currency mismatch")
    if consensus.available_at > actual.available_at:
        raise ValueError("consensus snapshot must be available before the actual")
    raw = metadata.directionality * (actual.actual - consensus.consensus)
    history = [abs(value) for value in historical_raw_surprises if value != 0]
    fallback = max(abs(consensus.consensus - consensus.previous_known), abs(consensus.consensus) * Decimal("0.01"), Decimal("0.0001"))
    scale = max(Decimal(str(median(history[-50:]))) if history else Decimal("0"), fallback)
    normalized = max(Decimal("-4"), min(Decimal("4"), raw / scale))
    revision = metadata.directionality * (actual.revised_previous - consensus.previous_known) / scale
    combined = max(Decimal("-4"), min(Decimal("4"), normalized + revision * Decimal("0.35")))
    return ReleaseSurprise(raw, normalized, revision, combined, scale)


@dataclass(frozen=True, slots=True)
class NewsDocument:
    document_id: str
    headline: str
    body: str
    source: str
    published_at: datetime
    received_at: datetime
    authority: Decimal = Decimal("0.5")

    def __post_init__(self) -> None:
        if self.published_at.tzinfo is None or self.received_at.tzinfo is None:
            raise ValueError("news timestamps must be timezone-aware")
        if self.received_at < self.published_at:
            raise ValueError("received_at cannot precede published_at")
        if not Decimal("0") <= self.authority <= Decimal("1"):
            raise ValueError("authority must be in [0,1]")

    @property
    def fingerprint(self) -> str:
        normalized = " ".join(self.headline.lower().split())
        return hashlib.sha256(normalized.encode()).hexdigest()[:24]


@dataclass(frozen=True, slots=True)
class NewsCluster:
    cluster_id: str
    earliest_publication: datetime
    documents: tuple[NewsDocument, ...]
    authoritative_source: str

    @property
    def source_count(self) -> int:
        return len({item.source for item in self.documents})


def cluster_news(documents: Iterable[NewsDocument]) -> tuple[NewsCluster, ...]:
    grouped: dict[str, list[NewsDocument]] = {}
    for document in documents:
        grouped.setdefault(document.fingerprint, []).append(document)
    clusters: list[NewsCluster] = []
    for fingerprint, items in grouped.items():
        ordered = sorted(items, key=lambda item: (item.published_at, item.received_at, item.document_id))
        authoritative = max(ordered, key=lambda item: (item.authority, -item.received_at.timestamp(), item.source))
        clusters.append(
            NewsCluster(
                cluster_id=f"news-{fingerprint}",
                earliest_publication=ordered[0].published_at,
                documents=tuple(ordered),
                authoritative_source=authoritative.source,
            )
        )
    return tuple(sorted(clusters, key=lambda item: (item.earliest_publication, item.cluster_id)))


@dataclass(frozen=True, slots=True)
class EvidenceSpan:
    start: int
    end: int
    text_hash: str

    @classmethod
    def from_text(cls, text: str, start: int, end: int) -> "EvidenceSpan":
        if not 0 <= start < end <= len(text):
            raise ValueError("invalid evidence span")
        return cls(start, end, hashlib.sha256(text[start:end].encode()).hexdigest())


@dataclass(frozen=True, slots=True)
class CentralBankExtraction:
    document_id: str
    institution: str
    currency: str
    event_type: str
    stance_delta: dict[str, Decimal]
    caveats: tuple[str, ...]
    evidence_spans: tuple[EvidenceSpan, ...]
    confidence: Decimal
    disposition: str
    prompt_version: str
    model_version: str

    def __post_init__(self) -> None:
        if self.disposition not in {"supported", "ambiguous", "contradictory", "abstain"}:
            raise ValueError("unsupported extraction disposition")
        if not Decimal("0") <= self.confidence <= Decimal("1"):
            raise ValueError("confidence must be in [0,1]")
        if any(not Decimal("-1") <= value <= Decimal("1") for value in self.stance_delta.values()):
            raise ValueError("stance deltas must be in [-1,1]")
