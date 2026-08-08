from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from enum import StrEnum
from typing import Mapping, Protocol
from urllib.parse import urlparse

import httpx

from forex_trader.intelligence.events import ConsensusSnapshot, ReleaseActual, ReleaseMetadata, ReleaseSurprise, calculate_release_surprise


def _normalize_host(host: str) -> str:
    normalized = host.strip().lower().rstrip(".")
    if normalized.startswith("www."):
        normalized = normalized[4:]
    if not normalized or "/" in normalized or ":" in normalized:
        raise ValueError(f"invalid source host: {host!r}")
    return normalized


def _validate_sha256(value: str, name: str) -> None:
    if len(value) != 64:
        raise ValueError(f"{name} must be a SHA-256 hex digest")
    try:
        int(value, 16)
    except ValueError as exc:
        raise ValueError(f"{name} must be a SHA-256 hex digest") from exc


class SourceAuthority(StrEnum):
    OFFICIAL = "official"
    LICENSED = "licensed"


@dataclass(frozen=True, slots=True)
class SourceDescriptor:
    source_id: str
    publisher: str
    authority: SourceAuthority
    allowed_hosts: frozenset[str]

    def __post_init__(self) -> None:
        if not self.source_id.strip() or not self.publisher.strip():
            raise ValueError("source_id and publisher are required")
        if not self.allowed_hosts:
            raise ValueError("allowed_hosts cannot be empty")
        object.__setattr__(self, "allowed_hosts", frozenset(_normalize_host(item) for item in self.allowed_hosts))

    def permits(self, url: str) -> bool:
        parsed = urlparse(url)
        if parsed.scheme.lower() != "https" or parsed.hostname is None:
            return False
        host = _normalize_host(parsed.hostname)
        return any(host == allowed or host.endswith(f".{allowed}") for allowed in self.allowed_hosts)


OFFICIAL_MACRO_SOURCES: Mapping[str, SourceDescriptor] = {
    "federal_reserve": SourceDescriptor(
        "federal_reserve",
        "Board of Governors of the Federal Reserve System",
        SourceAuthority.OFFICIAL,
        frozenset({"federalreserve.gov"}),
    ),
    "ecb": SourceDescriptor(
        "ecb",
        "European Central Bank",
        SourceAuthority.OFFICIAL,
        frozenset({"ecb.europa.eu", "data.ecb.europa.eu"}),
    ),
    "bank_of_england": SourceDescriptor(
        "bank_of_england",
        "Bank of England",
        SourceAuthority.OFFICIAL,
        frozenset({"bankofengland.co.uk"}),
    ),
    "bank_of_japan": SourceDescriptor(
        "bank_of_japan",
        "Bank of Japan",
        SourceAuthority.OFFICIAL,
        frozenset({"boj.or.jp"}),
    ),
    "bls": SourceDescriptor(
        "bls",
        "U.S. Bureau of Labor Statistics",
        SourceAuthority.OFFICIAL,
        frozenset({"bls.gov"}),
    ),
    "bea": SourceDescriptor(
        "bea",
        "U.S. Bureau of Economic Analysis",
        SourceAuthority.OFFICIAL,
        frozenset({"bea.gov"}),
    ),
    "census": SourceDescriptor(
        "census",
        "U.S. Census Bureau",
        SourceAuthority.OFFICIAL,
        frozenset({"census.gov"}),
    ),
    "statistics_canada": SourceDescriptor(
        "statistics_canada",
        "Statistics Canada",
        SourceAuthority.OFFICIAL,
        frozenset({"statcan.gc.ca"}),
    ),
    "australian_bureau_statistics": SourceDescriptor(
        "australian_bureau_statistics",
        "Australian Bureau of Statistics",
        SourceAuthority.OFFICIAL,
        frozenset({"abs.gov.au"}),
    ),
    "stats_nz": SourceDescriptor(
        "stats_nz",
        "Stats NZ",
        SourceAuthority.OFFICIAL,
        frozenset({"stats.govt.nz"}),
    ),
}


@dataclass(frozen=True, slots=True)
class RawSourcePayload:
    source_id: str
    publisher: str
    authority: SourceAuthority
    url: str
    content_type: str
    retrieved_at: datetime
    published_at: datetime
    available_at: datetime
    payload_sha256: str
    body: bytes

    def __post_init__(self) -> None:
        for name, value in (
            ("retrieved_at", self.retrieved_at),
            ("published_at", self.published_at),
            ("available_at", self.available_at),
        ):
            if value.tzinfo is None:
                raise ValueError(f"{name} must be timezone-aware")
        if self.available_at < self.published_at:
            raise ValueError("available_at cannot precede published_at")
        if self.retrieved_at < self.available_at:
            raise ValueError("retrieved_at cannot precede available_at")
        _validate_sha256(self.payload_sha256, "payload_sha256")
        if hashlib.sha256(self.body).hexdigest() != self.payload_sha256:
            raise ValueError("payload_sha256 does not match body")

    @property
    def record_id(self) -> str:
        payload = {
            "source_id": self.source_id,
            "publisher": self.publisher,
            "authority": self.authority.value,
            "url": self.url,
            "content_type": self.content_type,
            "retrieved_at": self.retrieved_at.isoformat(),
            "published_at": self.published_at.isoformat(),
            "available_at": self.available_at.isoformat(),
            "payload_sha256": self.payload_sha256,
        }
        encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
        return hashlib.sha256(encoded).hexdigest()

    @classmethod
    def create(
        cls,
        *,
        descriptor: SourceDescriptor,
        url: str,
        body: bytes,
        content_type: str,
        retrieved_at: datetime,
        published_at: datetime,
        available_at: datetime | None = None,
    ) -> RawSourcePayload:
        if not descriptor.permits(url):
            raise ValueError(f"URL is not permitted for source {descriptor.source_id}: {url}")
        return cls(
            source_id=descriptor.source_id,
            publisher=descriptor.publisher,
            authority=descriptor.authority,
            url=url,
            content_type=content_type.strip().lower() or "application/octet-stream",
            retrieved_at=retrieved_at,
            published_at=published_at,
            available_at=published_at if available_at is None else available_at,
            payload_sha256=hashlib.sha256(body).hexdigest(),
            body=body,
        )


@dataclass(frozen=True, slots=True)
class HttpPayload:
    status_code: int
    headers: Mapping[str, str]
    body: bytes
    final_url: str


class HttpTransport(Protocol):
    def get(self, url: str, *, timeout_seconds: float) -> HttpPayload: ...


class HttpxReadOnlyTransport:
    def get(self, url: str, *, timeout_seconds: float) -> HttpPayload:
        with httpx.Client(follow_redirects=False, timeout=timeout_seconds) as client:
            response = client.get(url, headers={"User-Agent": "forex-trader/official-source"})
        return HttpPayload(
            response.status_code,
            {key.lower(): value for key, value in response.headers.items()},
            response.content,
            str(response.url),
        )


@dataclass(frozen=True, slots=True)
class OfficialSourceClient:
    descriptor: SourceDescriptor
    transport: HttpTransport
    maximum_payload_bytes: int = 2_000_000
    timeout_seconds: float = 10.0

    def __post_init__(self) -> None:
        if self.descriptor.authority is not SourceAuthority.OFFICIAL:
            raise ValueError("OfficialSourceClient requires OFFICIAL source authority")
        if self.maximum_payload_bytes < 1 or self.timeout_seconds <= 0:
            raise ValueError("payload limit and timeout must be positive")

    def fetch(
        self,
        url: str,
        *,
        retrieved_at: datetime,
        published_at: datetime,
        available_at: datetime | None = None,
    ) -> RawSourcePayload:
        if not self.descriptor.permits(url):
            raise ValueError(f"URL is not permitted for source {self.descriptor.source_id}: {url}")
        response = self.transport.get(url, timeout_seconds=self.timeout_seconds)
        if response.status_code != 200:
            raise RuntimeError(f"official source returned HTTP {response.status_code}")
        if not self.descriptor.permits(response.final_url):
            raise RuntimeError("official source response escaped the approved publisher host")
        if len(response.body) > self.maximum_payload_bytes:
            raise RuntimeError("official source payload exceeds configured maximum size")
        content_type = response.headers.get("content-type", "application/octet-stream").split(";", 1)[0]
        return RawSourcePayload.create(
            descriptor=self.descriptor,
            url=response.final_url,
            body=response.body,
            content_type=content_type,
            retrieved_at=retrieved_at,
            published_at=published_at,
            available_at=available_at,
        )


@dataclass(frozen=True, slots=True)
class EconomicEventMapping:
    mapping_id: str
    indicator: str
    currency: str
    consensus_source_id: str
    official_source_id: str
    directionality: Decimal
    unit: str
    importance: Decimal = Decimal("1")

    def __post_init__(self) -> None:
        required = (
            self.mapping_id,
            self.indicator,
            self.currency,
            self.consensus_source_id,
            self.official_source_id,
            self.unit,
        )
        if any(not item.strip() for item in required):
            raise ValueError("economic event mapping identity fields are required")
        if len(self.currency.strip()) != 3:
            raise ValueError("currency must be a three-letter code")
        if self.directionality not in {Decimal("-1"), Decimal("1")}:
            raise ValueError("directionality must be -1 or 1")
        if not Decimal("0") < self.importance <= Decimal("1"):
            raise ValueError("importance must be in (0,1]")

    @property
    def metadata(self) -> ReleaseMetadata:
        return ReleaseMetadata(self.indicator, self.currency.upper(), self.directionality, unit=self.unit)


@dataclass(frozen=True, slots=True)
class LicensedConsensusEvidence:
    source: RawSourcePayload
    snapshot: ConsensusSnapshot
    scheduled_at: datetime

    def __post_init__(self) -> None:
        if self.source.authority is not SourceAuthority.LICENSED:
            raise ValueError("consensus evidence requires LICENSED source authority")
        if self.scheduled_at.tzinfo is None:
            raise ValueError("scheduled_at must be timezone-aware")
        if self.snapshot.available_at > self.scheduled_at:
            raise ValueError("consensus snapshot must be available no later than the scheduled release")
        if self.snapshot.source != self.source.source_id:
            raise ValueError("consensus snapshot source does not match raw source")


@dataclass(frozen=True, slots=True)
class OfficialReleaseEvidence:
    source: RawSourcePayload
    actual: ReleaseActual
    scheduled_at: datetime

    def __post_init__(self) -> None:
        if self.source.authority is not SourceAuthority.OFFICIAL:
            raise ValueError("release evidence requires OFFICIAL source authority")
        if self.scheduled_at.tzinfo is None:
            raise ValueError("scheduled_at must be timezone-aware")
        if self.actual.available_at < self.scheduled_at:
            raise ValueError("official actual cannot be available before the scheduled release")
        if self.actual.source != self.source.source_id:
            raise ValueError("release actual source does not match raw source")


def validate_and_calculate_release(
    mapping: EconomicEventMapping,
    consensus: LicensedConsensusEvidence,
    official: OfficialReleaseEvidence,
    *,
    historical_raw_surprises: tuple[Decimal, ...] = (),
) -> ReleaseSurprise:
    if consensus.source.source_id != mapping.consensus_source_id:
        raise ValueError("consensus source does not match event mapping")
    if official.source.source_id != mapping.official_source_id:
        raise ValueError("official source does not match event mapping")
    if consensus.scheduled_at != official.scheduled_at:
        raise ValueError("consensus and official scheduled timestamps do not match")
    if mapping.indicator != consensus.snapshot.indicator or mapping.indicator != official.actual.indicator:
        raise ValueError("indicator does not match event mapping")
    if mapping.currency.upper() != consensus.snapshot.currency.upper() or mapping.currency.upper() != official.actual.currency.upper():
        raise ValueError("currency does not match event mapping")
    return calculate_release_surprise(
        mapping.metadata,
        consensus.snapshot,
        official.actual,
        historical_raw_surprises=historical_raw_surprises,
    )
