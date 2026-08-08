from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime
from typing import Mapping, Protocol

import httpx

from forex_trader.ingestion.official_sources import RawSourcePayload, SourceAuthority, SourceDescriptor


@dataclass(frozen=True, slots=True)
class JsonPostPayload:
    status_code: int
    headers: Mapping[str, str]
    body: bytes
    final_url: str


class JsonPostTransport(Protocol):
    def post(self, url: str, *, body: bytes, timeout_seconds: float) -> JsonPostPayload: ...


class HttpxJsonPostTransport:
    """Read-only data query transport. POST is used only because the official API requires it."""

    def post(self, url: str, *, body: bytes, timeout_seconds: float) -> JsonPostPayload:
        with httpx.Client(follow_redirects=False, timeout=timeout_seconds) as client:
            response = client.post(
                url,
                content=body,
                headers={
                    "Content-Type": "application/json",
                    "User-Agent": "forex-trader/official-data-query",
                },
            )
        return JsonPostPayload(
            status_code=response.status_code,
            headers={key.lower(): value for key, value in response.headers.items()},
            body=response.content,
            final_url=str(response.url),
        )


@dataclass(frozen=True, slots=True)
class OfficialJsonQueryResponse:
    source: RawSourcePayload
    request_sha256: str
    request_body: bytes

    def __post_init__(self) -> None:
        if self.source.authority is not SourceAuthority.OFFICIAL:
            raise ValueError("official JSON response requires OFFICIAL source authority")
        if hashlib.sha256(self.request_body).hexdigest() != self.request_sha256:
            raise ValueError("request_sha256 does not match canonical request body")

    def json_object(self) -> dict[str, object]:
        try:
            value = json.loads(self.source.body)
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ValueError("official JSON response is not valid JSON") from exc
        if not isinstance(value, dict):
            raise ValueError("official JSON response root must be an object")
        return {str(key): item for key, item in value.items()}


@dataclass(frozen=True, slots=True)
class OfficialJsonPostClient:
    descriptor: SourceDescriptor
    transport: JsonPostTransport
    maximum_payload_bytes: int = 2_000_000
    timeout_seconds: float = 10.0

    def __post_init__(self) -> None:
        if self.descriptor.authority is not SourceAuthority.OFFICIAL:
            raise ValueError("OfficialJsonPostClient requires OFFICIAL source authority")
        if self.maximum_payload_bytes < 1:
            raise ValueError("maximum_payload_bytes must be positive")
        if self.timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be positive")

    def query(
        self,
        url: str,
        payload: Mapping[str, object],
        *,
        retrieved_at: datetime,
    ) -> OfficialJsonQueryResponse:
        if retrieved_at.tzinfo is None:
            raise ValueError("retrieved_at must be timezone-aware")
        if not self.descriptor.permits(url):
            raise ValueError(f"URL is not permitted for source {self.descriptor.source_id}: {url}")
        body = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
        response = self.transport.post(url, body=body, timeout_seconds=self.timeout_seconds)
        if response.status_code != 200:
            raise RuntimeError(f"official JSON source returned HTTP {response.status_code}")
        if not self.descriptor.permits(response.final_url):
            raise RuntimeError("official JSON response escaped the approved publisher host")
        if len(response.body) > self.maximum_payload_bytes:
            raise RuntimeError("official JSON response exceeds configured maximum size")
        content_type = response.headers.get("content-type", "application/json").split(";", 1)[0]
        source = RawSourcePayload.create(
            descriptor=self.descriptor,
            url=response.final_url,
            body=response.body,
            content_type=content_type,
            retrieved_at=retrieved_at,
            published_at=retrieved_at,
            available_at=retrieved_at,
        )
        return OfficialJsonQueryResponse(
            source=source,
            request_sha256=hashlib.sha256(body).hexdigest(),
            request_body=body,
        )
