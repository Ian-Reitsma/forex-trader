from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from forex_trader.research.replay_archive import EXECUTABLE_QUOTE_EVENT, canonical_payload_sha256, file_sha256


def _build_archive(tmp_path: Path) -> Path:
    payload = {
        "instrument": "EUR_USD",
        "bid": "1.1000",
        "ask": "1.1002",
        "tradeable": True,
    }
    record = {
        "event_id": "quote-1",
        "event_type": EXECUTABLE_QUOTE_EVENT,
        "occurred_at": "2026-08-07T12:00:01+00:00",
        "available_at": "2026-08-07T12:00:01+00:00",
        "provider": "broker-archive",
        "channel": "pricing",
        "provider_sequence": 1,
        "payload": payload,
        "payload_sha256": canonical_payload_sha256(payload),
    }
    source = tmp_path / "quotes.jsonl"
    source.write_text(json.dumps(record, sort_keys=True) + "\n")
    manifest = {
        "schema_version": "1.0",
        "dataset_id": "cli-replay-test",
        "created_at": "2026-08-07T13:00:00+00:00",
        "period_start": "2026-08-07T12:00:00+00:00",
        "period_end": "2026-08-07T12:30:00+00:00",
        "files": [
            {
                "path": source.name,
                "sha256": file_sha256(source),
                "event_types": [EXECUTABLE_QUOTE_EVENT],
            }
        ],
        "required_event_types": [EXECUTABLE_QUOTE_EVENT],
        "instruments": ["EUR_USD"],
    }
    path = tmp_path / "manifest.json"
    path.write_text(json.dumps(manifest, indent=2))
    return path


def test_validate_replay_archive_cli_stdout(tmp_path) -> None:  # type: ignore[no-untyped-def]
    manifest = _build_archive(tmp_path)
    result = subprocess.run(
        [sys.executable, "scripts/validate_replay_archive.py", str(manifest)],
        check=True,
        capture_output=True,
        text=True,
    )
    payload = json.loads(result.stdout)
    assert payload["status"] == "valid"
    assert payload["dataset_id"] == "cli-replay-test"
    assert payload["records"] == 1
    assert payload["event_types"] == {EXECUTABLE_QUOTE_EVENT: 1}
    assert payload["providers"] == {"broker-archive": 1}
    assert payload["quote_instruments"] == {"EUR_USD": 1}
    assert len(payload["manifest_hash"]) == 64
    assert len(payload["archive_hash"]) == 64


def test_validate_replay_archive_cli_output_file(tmp_path) -> None:  # type: ignore[no-untyped-def]
    manifest = _build_archive(tmp_path)
    output = tmp_path / "validation.json"
    result = subprocess.run(
        [
            sys.executable,
            "scripts/validate_replay_archive.py",
            str(manifest),
            "--output",
            str(output),
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    assert result.stdout == ""
    payload = json.loads(output.read_text())
    assert payload["status"] == "valid"
    assert payload["required_event_types"] == [EXECUTABLE_QUOTE_EVENT]
