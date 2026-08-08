from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

import pytest

from forex_trader.research.replay_archive import (
    EXECUTABLE_QUOTE_EVENT,
    ArchivedReplayRecord,
    ExecutableQuoteTick,
    PointInTimeExecutableQuoteBook,
    ReplayArchiveBundle,
    ReplayArchiveManifest,
    ReplaySourceFile,
    canonical_payload_sha256,
    file_sha256,
)

NOW = datetime(2026, 8, 7, 12, 0, tzinfo=UTC)


def _record(
    event_id: str,
    event_type: str,
    *,
    sequence: int,
    seconds: int,
    provider: str = "test-provider",
    channel: str = "quotes",
    payload: dict[str, object] | None = None,
) -> dict[str, object]:
    body = payload or {"value": event_id}
    instant = NOW + timedelta(seconds=seconds)
    return {
        "event_id": event_id,
        "event_type": event_type,
        "occurred_at": instant.isoformat(),
        "available_at": instant.isoformat(),
        "provider": provider,
        "channel": channel,
        "provider_sequence": sequence,
        "payload": body,
        "payload_sha256": canonical_payload_sha256(body),
    }


def _quote_record(
    event_id: str,
    *,
    sequence: int,
    seconds: int,
    bid: str = "1.1000",
    ask: str = "1.1002",
    tradeable: bool = True,
) -> dict[str, object]:
    return _record(
        event_id,
        EXECUTABLE_QUOTE_EVENT,
        sequence=sequence,
        seconds=seconds,
        provider="broker-archive",
        channel="pricing",
        payload={
            "instrument": "EUR_USD",
            "bid": bid,
            "ask": ask,
            "tradeable": tradeable,
        },
    )


def _write_jsonl(path: Path, rows: list[dict[str, object]]) -> None:
    path.write_text("".join(json.dumps(row, sort_keys=True) + "\n" for row in rows))


def _manifest_payload(
    files: list[dict[str, object]],
    *,
    required: list[str] | None = None,
    instruments: list[str] | None = None,
) -> dict[str, object]:
    return {
        "schema_version": "1.0",
        "dataset_id": "audit-replay-test",
        "created_at": (NOW + timedelta(hours=1)).isoformat(),
        "period_start": NOW.isoformat(),
        "period_end": (NOW + timedelta(minutes=30)).isoformat(),
        "files": files,
        "required_event_types": required or [EXECUTABLE_QUOTE_EVENT],
        "instruments": instruments or ["EUR_USD"],
    }


def _write_bundle(tmp_path: Path) -> Path:
    quotes = tmp_path / "quotes.jsonl"
    macro = tmp_path / "macro.jsonl"
    _write_jsonl(
        quotes,
        [
            _quote_record("q2", sequence=2, seconds=2),
            _quote_record("q1", sequence=1, seconds=1),
        ],
    )
    _write_jsonl(
        macro,
        [
            _record(
                "macro-1",
                "economic_actual",
                sequence=1,
                seconds=2,
                provider="calendar-vendor",
                channel="calendar",
                payload={"currency": "USD", "indicator": "CPI", "actual": "2.8"},
            )
        ],
    )
    manifest = tmp_path / "manifest.json"
    manifest.write_text(
        json.dumps(
            _manifest_payload(
                [
                    {
                        "path": quotes.name,
                        "sha256": file_sha256(quotes),
                        "event_types": [EXECUTABLE_QUOTE_EVENT],
                    },
                    {
                        "path": macro.name,
                        "sha256": file_sha256(macro),
                        "event_types": ["economic_actual"],
                    },
                ],
                required=[EXECUTABLE_QUOTE_EVENT, "economic_actual"],
            ),
            indent=2,
        )
    )
    return manifest


def test_manifest_and_source_contract_validation() -> None:
    with pytest.raises(ValueError, match="relative"):
        ReplaySourceFile("/tmp/quotes", "0" * 64, (EXECUTABLE_QUOTE_EVENT,))
    with pytest.raises(ValueError, match="64-character"):
        ReplaySourceFile("quotes.jsonl", "abc", (EXECUTABLE_QUOTE_EVENT,))
    with pytest.raises(ValueError, match="at least one event"):
        ReplaySourceFile("quotes.jsonl", "0" * 64, ())
    with pytest.raises(ValueError, match="non-empty"):
        ReplaySourceFile("quotes.jsonl", "0" * 64, ("",))

    source = ReplaySourceFile("quotes.jsonl", "0" * 64, (EXECUTABLE_QUOTE_EVENT,))
    with pytest.raises(ValueError, match="schema_version"):
        ReplayArchiveManifest("x", NOW, NOW, NOW + timedelta(seconds=1), (source,), ("x",), (), "9")
    with pytest.raises(ValueError, match="dataset_id"):
        ReplayArchiveManifest("", NOW, NOW, NOW + timedelta(seconds=1), (source,), ("x",), ())
    with pytest.raises(ValueError, match="timezone-aware"):
        ReplayArchiveManifest("x", NOW.replace(tzinfo=None), NOW, NOW + timedelta(seconds=1), (source,), ("x",), ())
    with pytest.raises(ValueError, match="after period_start"):
        ReplayArchiveManifest("x", NOW, NOW, NOW, (source,), ("x",), ())
    with pytest.raises(ValueError, match="source files"):
        ReplayArchiveManifest("x", NOW, NOW, NOW + timedelta(seconds=1), (), ("x",), ())
    with pytest.raises(ValueError, match="unique"):
        ReplayArchiveManifest("x", NOW, NOW, NOW + timedelta(seconds=1), (source, source), ("x",), ())
    with pytest.raises(ValueError, match="required_event_types"):
        ReplayArchiveManifest("x", NOW, NOW, NOW + timedelta(seconds=1), (source,), (), ())
    with pytest.raises(ValueError, match="BASE_QUOTE"):
        ReplayArchiveManifest("x", NOW, NOW, NOW + timedelta(seconds=1), (source,), ("x",), ("EURUSD",))
    with pytest.raises(ValueError, match="unique"):
        ReplayArchiveManifest("x", NOW, NOW, NOW + timedelta(seconds=1), (source,), ("x",), ("EUR_USD", "eur_usd"))


def test_record_and_quote_contracts_fail_closed() -> None:
    body = {"instrument": "EUR_USD", "bid": "1.1", "ask": "1.2"}
    digest = canonical_payload_sha256(body)
    with pytest.raises(ValueError, match="event_id"):
        ArchivedReplayRecord("", "x", NOW, NOW, "p", "c", 1, body, digest)
    with pytest.raises(ValueError, match="timezone-aware"):
        ArchivedReplayRecord("x", "x", NOW.replace(tzinfo=None), NOW, "p", "c", 1, body, digest)
    with pytest.raises(ValueError, match="provider and channel"):
        ArchivedReplayRecord("x", "x", NOW, NOW, "", "c", 1, body, digest)
    with pytest.raises(ValueError, match="negative"):
        ArchivedReplayRecord("x", "x", NOW, NOW, "p", "c", -1, body, digest)
    with pytest.raises(ValueError, match="hash mismatch"):
        ArchivedReplayRecord("x", "x", NOW, NOW, "p", "c", 1, body, "0" * 64)
    with pytest.raises(ValueError, match="payload must be an object"):
        ArchivedReplayRecord.from_payload({**_record("x", "x", sequence=1, seconds=0), "payload": []})

    record = ArchivedReplayRecord.from_payload(_quote_record("q", sequence=1, seconds=0))
    quote = ExecutableQuoteTick.from_record(record)
    assert quote.spread == Decimal("0.0002")
    assert quote.mid == Decimal("1.1001")
    with pytest.raises(ValueError, match="not an executable quote"):
        ExecutableQuoteTick.from_record(ArchivedReplayRecord.from_payload(_record("x", "news", sequence=1, seconds=0)))
    with pytest.raises(ValueError, match="bid <= ask"):
        ExecutableQuoteTick.from_record(ArchivedReplayRecord.from_payload(_quote_record("bad", sequence=2, seconds=1, bid="1.2", ask="1.1")))


def test_bundle_loads_verifies_and_orders_by_availability_sequence_event_id(tmp_path) -> None:  # type: ignore[no-untyped-def]
    manifest_path = _write_bundle(tmp_path)
    bundle = ReplayArchiveBundle.load(manifest_path)

    assert bundle.manifest.dataset_id == "audit-replay-test"
    assert len(bundle.records) == 3
    assert [record.event_id for record in bundle.records] == ["q1", "macro-1", "q2"]
    assert len(bundle.archive_hash) == 64
    assert len(bundle.manifest.manifest_hash) == 64

    scheduler = bundle.scheduler()
    assert scheduler.remaining == 3
    assert [event.event_id for event in scheduler.pop_until(NOW + timedelta(seconds=1))] == ["q1"]
    assert [event.event_id for event in scheduler.pop_until(NOW + timedelta(seconds=2))] == ["macro-1", "q2"]
    assert scheduler.remaining == 0

    assert [record.event_id for record in bundle.events_until(NOW + timedelta(seconds=1))] == ["q1"]
    with pytest.raises(ValueError, match="timezone-aware"):
        bundle.events_until(NOW.replace(tzinfo=None))


def test_point_in_time_quote_book_never_reaches_forward_or_interpolates(tmp_path) -> None:  # type: ignore[no-untyped-def]
    bundle = ReplayArchiveBundle.load(_write_bundle(tmp_path))
    book = bundle.quote_book()
    first = book.quote_at(
        "EUR_USD",
        as_of=NOW + timedelta(seconds=1, milliseconds=500),
        maximum_age_seconds=Decimal("1"),
    )
    assert first.event_id == "q1"

    with pytest.raises(LookupError, match="no point-in-time"):
        book.quote_at("EUR_USD", as_of=NOW, maximum_age_seconds=Decimal("5"))
    with pytest.raises(LookupError, match="stale"):
        book.quote_at("EUR_USD", as_of=NOW + timedelta(seconds=10), maximum_age_seconds=Decimal("2"))
    with pytest.raises(ValueError, match="timezone-aware"):
        book.quote_at("EUR_USD", as_of=NOW.replace(tzinfo=None), maximum_age_seconds=Decimal("2"))
    with pytest.raises(ValueError, match="positive"):
        book.quote_at("EUR_USD", as_of=NOW, maximum_age_seconds=Decimal("0"))

    nontradeable = ExecutableQuoteTick.from_record(
        ArchivedReplayRecord.from_payload(_quote_record("closed", sequence=9, seconds=9, tradeable=False))
    )
    closed_book = PointInTimeExecutableQuoteBook([nontradeable])
    with pytest.raises(LookupError, match="no point-in-time"):
        closed_book.quote_at(
            "EUR_USD",
            as_of=NOW + timedelta(seconds=9),
            maximum_age_seconds=Decimal("2"),
        )
    assert closed_book.quote_at(
        "EUR_USD",
        as_of=NOW + timedelta(seconds=9),
        maximum_age_seconds=Decimal("2"),
        require_tradeable=False,
    ).event_id == "closed"


def test_bundle_rejects_file_and_payload_tampering(tmp_path) -> None:  # type: ignore[no-untyped-def]
    manifest_path = _write_bundle(tmp_path)
    quotes = tmp_path / "quotes.jsonl"
    quotes.write_text(quotes.read_text() + "\n")
    with pytest.raises(ValueError, match="checksum mismatch"):
        ReplayArchiveBundle.load(manifest_path)

    manifest_path = _write_bundle(tmp_path)
    quotes = tmp_path / "quotes.jsonl"
    rows = [json.loads(line) for line in quotes.read_text().splitlines() if line.strip()]
    rows[0]["payload"]["bid"] = "1.0999"
    _write_jsonl(quotes, rows)
    manifest = json.loads(manifest_path.read_text())
    manifest["files"][0]["sha256"] = file_sha256(quotes)
    manifest_path.write_text(json.dumps(manifest))
    with pytest.raises(ValueError, match="payload hash mismatch"):
        ReplayArchiveBundle.load(manifest_path)


def test_bundle_rejects_duplicate_identity_sequence_and_schema_drift(tmp_path) -> None:  # type: ignore[no-untyped-def]
    source = tmp_path / "events.jsonl"
    duplicate_id = [
        _quote_record("same", sequence=1, seconds=1),
        _quote_record("same", sequence=2, seconds=2),
    ]
    _write_jsonl(source, duplicate_id)
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text(
        json.dumps(_manifest_payload([{"path": source.name, "sha256": file_sha256(source), "event_types": [EXECUTABLE_QUOTE_EVENT]}]))
    )
    with pytest.raises(ValueError, match="duplicate replay event_id"):
        ReplayArchiveBundle.load(manifest_path)

    duplicate_sequence = [
        _quote_record("a", sequence=1, seconds=1),
        _quote_record("b", sequence=1, seconds=2),
    ]
    _write_jsonl(source, duplicate_sequence)
    manifest_path.write_text(
        json.dumps(_manifest_payload([{"path": source.name, "sha256": file_sha256(source), "event_types": [EXECUTABLE_QUOTE_EVENT]}]))
    )
    with pytest.raises(ValueError, match="duplicate replay provider sequence"):
        ReplayArchiveBundle.load(manifest_path)

    wrong_type = [_record("x", "news", sequence=1, seconds=1)]
    _write_jsonl(source, wrong_type)
    manifest_path.write_text(
        json.dumps(_manifest_payload([{"path": source.name, "sha256": file_sha256(source), "event_types": [EXECUTABLE_QUOTE_EVENT]}]))
    )
    with pytest.raises(ValueError, match="not declared"):
        ReplayArchiveBundle.load(manifest_path)


def test_bundle_rejects_period_universe_missing_types_and_invalid_sources(tmp_path) -> None:  # type: ignore[no-untyped-def]
    source = tmp_path / "events.jsonl"
    outside = _quote_record("late", sequence=1, seconds=1900)
    _write_jsonl(source, [outside])
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text(
        json.dumps(_manifest_payload([{"path": source.name, "sha256": file_sha256(source), "event_types": [EXECUTABLE_QUOTE_EVENT]}]))
    )
    with pytest.raises(ValueError, match="outside manifest"):
        ReplayArchiveBundle.load(manifest_path)

    wrong_instrument = _quote_record("xau", sequence=1, seconds=1)
    wrong_instrument["payload"]["instrument"] = "GBP_USD"  # type: ignore[index]
    wrong_instrument["payload_sha256"] = canonical_payload_sha256(wrong_instrument["payload"])  # type: ignore[arg-type]
    _write_jsonl(source, [wrong_instrument])
    manifest_path.write_text(
        json.dumps(_manifest_payload([{"path": source.name, "sha256": file_sha256(source), "event_types": [EXECUTABLE_QUOTE_EVENT]}]))
    )
    with pytest.raises(ValueError, match="outside the manifest universe"):
        ReplayArchiveBundle.load(manifest_path)

    _write_jsonl(source, [_quote_record("q", sequence=1, seconds=1)])
    manifest_path.write_text(
        json.dumps(
            _manifest_payload(
                [{"path": source.name, "sha256": file_sha256(source), "event_types": [EXECUTABLE_QUOTE_EVENT]}],
                required=[EXECUTABLE_QUOTE_EVENT, "news"],
            )
        )
    )
    with pytest.raises(ValueError, match="missing required event types"):
        ReplayArchiveBundle.load(manifest_path)

    manifest = json.loads(manifest_path.read_text())
    manifest["files"][0]["path"] = "../escape.jsonl"
    manifest_path.write_text(json.dumps(manifest))
    with pytest.raises(ValueError, match="escapes manifest directory|does not exist"):
        ReplayArchiveBundle.load(manifest_path)

    missing_manifest = tmp_path / "missing-manifest.json"
    missing_manifest.write_text(json.dumps(_manifest_payload([{"path": "missing.jsonl", "sha256": "0" * 64, "event_types": [EXECUTABLE_QUOTE_EVENT]}])))
    with pytest.raises(ValueError, match="does not exist"):
        ReplayArchiveBundle.load(missing_manifest)


def test_manifest_payload_parser_and_archive_json_validation(tmp_path) -> None:  # type: ignore[no-untyped-def]
    with pytest.raises(ValueError, match="files must be a list"):
        ReplayArchiveManifest.from_payload({"files": "bad"})
    payload = _manifest_payload([])
    payload["files"] = ["bad"]
    with pytest.raises(ValueError, match="file entries"):
        ReplayArchiveManifest.from_payload(payload)
    payload["files"] = [{"path": "x", "sha256": "0" * 64, "event_types": "bad"}]
    with pytest.raises(ValueError, match="event_types must be a list"):
        ReplayArchiveManifest.from_payload(payload)
    payload["files"] = [{"path": "x", "sha256": "0" * 64, "event_types": ["x"]}]
    payload["required_event_types"] = "bad"
    with pytest.raises(ValueError, match="must be lists"):
        ReplayArchiveManifest.from_payload(payload)

    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text("[]")
    with pytest.raises(ValueError, match="JSON object"):
        ReplayArchiveBundle.load(manifest_path)

    source = tmp_path / "bad.jsonl"
    source.write_text("not-json\n")
    manifest_path.write_text(
        json.dumps(_manifest_payload([{"path": source.name, "sha256": file_sha256(source), "event_types": [EXECUTABLE_QUOTE_EVENT]}]))
    )
    with pytest.raises(ValueError, match="invalid JSONL"):
        ReplayArchiveBundle.load(manifest_path)

    source.write_text("[]\n")
    manifest_path.write_text(
        json.dumps(_manifest_payload([{"path": source.name, "sha256": file_sha256(source), "event_types": [EXECUTABLE_QUOTE_EVENT]}]))
    )
    with pytest.raises(ValueError, match="must be a JSON object"):
        ReplayArchiveBundle.load(manifest_path)
