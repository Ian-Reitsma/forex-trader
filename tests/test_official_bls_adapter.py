from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from decimal import Decimal

import pytest

from forex_trader.ingestion.bls import BLS_PUBLIC_DATA_V2_URL, BlsPublicDataAdapter, BlsQuery
from forex_trader.ingestion.official_json import JsonPostPayload, OfficialJsonPostClient, OfficialJsonQueryResponse
from forex_trader.ingestion.official_sources import OFFICIAL_MACRO_SOURCES, RawSourcePayload, SourceAuthority, SourceDescriptor


NOW = datetime(2026, 8, 7, 15, 0, tzinfo=UTC)
BLS = OFFICIAL_MACRO_SOURCES["bls"]


class Transport:
    def __init__(self, response: JsonPostPayload) -> None:
        self.response = response
        self.calls: list[tuple[str, bytes, float]] = []

    def post(self, url: str, *, body: bytes, timeout_seconds: float) -> JsonPostPayload:
        self.calls.append((url, body, timeout_seconds))
        return self.response


def response(payload: object, *, status_code: int = 200, final_url: str = BLS_PUBLIC_DATA_V2_URL) -> JsonPostPayload:
    return JsonPostPayload(
        status_code=status_code,
        headers={"content-type": "application/json; charset=utf-8"},
        body=json.dumps(payload, separators=(",", ":")).encode(),
        final_url=final_url,
    )


def success_payload(*, series_id: str = "CUUR0000SA0") -> dict[str, object]:
    return {
        "status": "REQUEST_SUCCEEDED",
        "responseTime": 17,
        "message": [],
        "Results": {
            "series": [
                {
                    "seriesID": series_id,
                    "data": [
                        {
                            "year": "2026",
                            "period": "M06",
                            "periodName": "June",
                            "latest": "true",
                            "value": "322.561",
                            "footnotes": [{"code": "P", "text": "Preliminary."}],
                        }
                    ],
                }
            ]
        },
    }


def test_official_json_post_client_binds_canonical_request_and_raw_response() -> None:
    transport = Transport(response(success_payload()))
    client = OfficialJsonPostClient(BLS, transport)
    request = {"startyear": "2026", "seriesid": ["CUUR0000SA0"], "endyear": "2026"}
    result = client.query(BLS_PUBLIC_DATA_V2_URL, request, retrieved_at=NOW)

    expected_body = b'{"endyear":"2026","seriesid":["CUUR0000SA0"],"startyear":"2026"}'
    assert result.request_body == expected_body
    assert result.request_sha256 == hashlib.sha256(expected_body).hexdigest()
    assert result.source.source_id == "bls"
    assert result.source.authority is SourceAuthority.OFFICIAL
    assert result.source.available_at == NOW
    assert transport.calls == [(BLS_PUBLIC_DATA_V2_URL, expected_body, 10.0)]
    assert result.json_object()["status"] == "REQUEST_SUCCEEDED"


def test_official_json_post_client_fails_closed_on_config_host_status_size_and_json() -> None:
    licensed = SourceDescriptor("licensed", "Vendor", SourceAuthority.LICENSED, frozenset({"vendor.example"}))
    ok_transport = Transport(response(success_payload()))
    with pytest.raises(ValueError, match="OFFICIAL"):
        OfficialJsonPostClient(licensed, ok_transport)
    with pytest.raises(ValueError, match="positive"):
        OfficialJsonPostClient(BLS, ok_transport, maximum_payload_bytes=0)
    with pytest.raises(ValueError, match="positive"):
        OfficialJsonPostClient(BLS, ok_transport, timeout_seconds=0)

    client = OfficialJsonPostClient(BLS, ok_transport)
    with pytest.raises(ValueError, match="timezone-aware"):
        client.query(BLS_PUBLIC_DATA_V2_URL, {}, retrieved_at=NOW.replace(tzinfo=None))
    with pytest.raises(ValueError, match="not permitted"):
        client.query("https://evil.example/api", {}, retrieved_at=NOW)

    bad_status = OfficialJsonPostClient(BLS, Transport(response({}, status_code=429)))
    with pytest.raises(RuntimeError, match="HTTP 429"):
        bad_status.query(BLS_PUBLIC_DATA_V2_URL, {}, retrieved_at=NOW)

    escaped = OfficialJsonPostClient(BLS, Transport(response({}, final_url="https://evil.example/x")))
    with pytest.raises(RuntimeError, match="escaped"):
        escaped.query(BLS_PUBLIC_DATA_V2_URL, {}, retrieved_at=NOW)

    oversized = OfficialJsonPostClient(BLS, Transport(response(success_payload())), maximum_payload_bytes=5)
    with pytest.raises(RuntimeError, match="maximum size"):
        oversized.query(BLS_PUBLIC_DATA_V2_URL, {}, retrieved_at=NOW)

    raw = RawSourcePayload.create(
        descriptor=BLS,
        url=BLS_PUBLIC_DATA_V2_URL,
        body=b"not-json",
        content_type="application/json",
        retrieved_at=NOW,
        published_at=NOW,
        available_at=NOW,
    )
    envelope = OfficialJsonQueryResponse(raw, hashlib.sha256(b"{}").hexdigest(), b"{}")
    with pytest.raises(ValueError, match="valid JSON"):
        envelope.json_object()
    with pytest.raises(ValueError, match="request_sha256"):
        OfficialJsonQueryResponse(raw, "0" * 64, b"{}")


def test_bls_query_uses_conservative_public_bounds_and_canonical_payload() -> None:
    query = BlsQuery(("CUUR0000SA0", "CES0000000001"), 2020, 2026)
    assert query.payload() == {
        "seriesid": ["CUUR0000SA0", "CES0000000001"],
        "startyear": "2020",
        "endyear": "2026",
    }
    with pytest.raises(ValueError, match="at least one"):
        BlsQuery((), 2026, 2026)
    with pytest.raises(ValueError, match="25"):
        BlsQuery(tuple(f"SERIES{i:02d}" for i in range(26)), 2026, 2026)
    with pytest.raises(ValueError, match="unique"):
        BlsQuery(("CUUR0000SA0", "CUUR0000SA0"), 2026, 2026)
    with pytest.raises(ValueError, match="uppercase"):
        BlsQuery(("cuur0000sa0",), 2026, 2026)
    with pytest.raises(ValueError, match="year range"):
        BlsQuery(("CUUR0000SA0",), 2027, 2026)
    with pytest.raises(ValueError, match="10-year"):
        BlsQuery(("CUUR0000SA0",), 2016, 2026)


def test_bls_adapter_parses_decimal_period_latest_and_footnotes() -> None:
    transport = Transport(response(success_payload()))
    adapter = BlsPublicDataAdapter(OfficialJsonPostClient(BLS, transport))
    result = adapter.fetch(BlsQuery(("CUUR0000SA0",), 2026, 2026), retrieved_at=NOW)

    assert result.response_time_ms == 17
    assert result.messages == ()
    assert len(result.observations) == 1
    item = result.observations[0]
    assert item.series_id == "CUUR0000SA0"
    assert item.year == 2026
    assert item.period == "M06"
    assert item.period_name == "June"
    assert item.value == Decimal("322.561")
    assert item.latest is True
    assert [(note.code, note.text) for note in item.footnotes] == [("P", "Preliminary.")]


def test_bls_adapter_rejects_noncanonical_descriptor_and_api_level_failure() -> None:
    clone = SourceDescriptor("bls", "Different Publisher", SourceAuthority.OFFICIAL, frozenset({"bls.gov"}))
    with pytest.raises(ValueError, match="canonical"):
        BlsPublicDataAdapter(OfficialJsonPostClient(clone, Transport(response(success_payload()))))

    failure = {
        "status": "REQUEST_FAILED",
        "message": ["Series does not exist"],
        "Results": {},
    }
    adapter = BlsPublicDataAdapter(OfficialJsonPostClient(BLS, Transport(response(failure))))
    with pytest.raises(RuntimeError, match="Series does not exist"):
        adapter.fetch(BlsQuery(("CUUR0000SA0",), 2026, 2026), retrieved_at=NOW)


def test_bls_adapter_rejects_unrequested_duplicate_missing_and_malformed_series() -> None:
    query = BlsQuery(("CUUR0000SA0",), 2026, 2026)

    unrequested = BlsPublicDataAdapter(
        OfficialJsonPostClient(BLS, Transport(response(success_payload(series_id="CES0000000001"))))
    )
    with pytest.raises(ValueError, match="unrequested"):
        unrequested.fetch(query, retrieved_at=NOW)

    duplicate_payload = success_payload()
    duplicate_payload["Results"] = {
        "series": [
            success_payload()["Results"]["series"][0],  # type: ignore[index]
            success_payload()["Results"]["series"][0],  # type: ignore[index]
        ]
    }
    duplicate = BlsPublicDataAdapter(OfficialJsonPostClient(BLS, Transport(response(duplicate_payload))))
    with pytest.raises(ValueError, match="duplicate"):
        duplicate.fetch(query, retrieved_at=NOW)

    missing_payload = {"status": "REQUEST_SUCCEEDED", "message": [], "Results": {"series": []}}
    missing = BlsPublicDataAdapter(OfficialJsonPostClient(BLS, Transport(response(missing_payload))))
    with pytest.raises(ValueError, match="omitted"):
        missing.fetch(query, retrieved_at=NOW)

    malformed_payload = success_payload()
    malformed_payload["Results"] = {"series": [{"seriesID": "CUUR0000SA0", "data": [{"year": "x"}]}]}
    malformed = BlsPublicDataAdapter(OfficialJsonPostClient(BLS, Transport(response(malformed_payload))))
    with pytest.raises(ValueError, match="invalid year"):
        malformed.fetch(query, retrieved_at=NOW)
