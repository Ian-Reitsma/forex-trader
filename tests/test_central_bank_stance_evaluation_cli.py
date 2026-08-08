from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

from forex_trader.infrastructure.official_document_repository import OfficialDocumentRepository
from forex_trader.intelligence.official_documents import OfficialDocumentVersion


BASE = datetime(2026, 1, 1, tzinfo=UTC)


def version(*, suffix: str, text: str, predecessor: str | None, at: datetime) -> OfficialDocumentVersion:
    return OfficialDocumentVersion(
        family_id="fed_fomc_statement",
        source_id="federal_reserve",
        document_type="monetary_policy_statement",
        institution="Federal Reserve",
        currency="USD",
        discovery_id=hashlib.sha256(f"discovery-{suffix}".encode()).hexdigest(),
        item_id=f"item-{suffix}",
        document_url=f"https://www.federalreserve.gov/{suffix}.htm",
        published_at=at - timedelta(seconds=1),
        available_at=at,
        source_record_id=hashlib.sha256(f"record-{suffix}".encode()).hexdigest(),
        source_payload_sha256=hashlib.sha256(f"payload-{suffix}".encode()).hexdigest(),
        text_sha256=hashlib.sha256(text.encode()).hexdigest(),
        text=text,
        predecessor_version_id=predecessor,
    )


def test_evaluation_cli_emits_research_only_report_and_baselines(tmp_path: Path) -> None:
    database = tmp_path / "documents.db"
    repository = OfficialDocumentRepository(database)
    first = version(suffix="first", text="Inflation remains elevated.", predecessor=None, at=BASE)
    repository.append(first)
    second = version(
        suffix="second",
        text="Inflation has eased.",
        predecessor=first.version_id,
        at=BASE + timedelta(minutes=1),
    )
    repository.append(second)

    labels = tmp_path / "labels.jsonl"
    labels.write_text(
        json.dumps(
            {
                "family_id": first.family_id,
                "previous_version_id": first.version_id,
                "current_version_id": second.version_id,
                "expected_direction": "dovish",
                "expected_disposition": "supported",
                "label_source_id": "human-review-batch-001",
                "dimensions": [{"dimension": "inflation", "direction": "dovish"}],
            }
        )
        + "\n",
        encoding="utf-8",
    )
    output = tmp_path / "report.json"
    completed = subprocess.run(
        [
            sys.executable,
            "scripts/evaluate_central_bank_stance.py",
            str(database),
            str(labels),
            "--output",
            str(output),
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    payload = json.loads(output.read_text(encoding="utf-8"))
    printed = json.loads(completed.stdout)
    assert payload == printed
    assert payload["research_only"] is True
    assert payload["execution_authority"] is False
    assert len(payload["dataset_id"]) == 64
    assert payload["report"]["ruleset_version"] == "central-bank-statement-rules-v1"
    assert payload["report"]["exact_accuracy"] == "1"
    assert payload["report"]["dimension_accuracy"] == "1"
    assert [item["name"] for item in payload["baselines"]] == [
        "always_abstain",
        "always_hawkish",
        "always_dovish",
    ]
    assert "does not grant runtime or execution authority" in payload["interpretation"]
