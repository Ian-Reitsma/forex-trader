"""Produce source-backed research-only stance evidence from persisted official document versions."""
from __future__ import annotations

import argparse
import json
from dataclasses import asdict
from decimal import Decimal
from enum import Enum
from pathlib import Path

from forex_trader.infrastructure.official_document_repository import OfficialDocumentRepository
from forex_trader.intelligence.official_documents import compare_document_versions
from forex_trader.research.central_bank_stance import CentralBankStanceEvidence, extract_central_bank_stance


def analyze_stance(
    database: Path,
    *,
    family_id: str,
    current_version_id: str | None = None,
) -> CentralBankStanceEvidence:
    requested_family = family_id.strip()
    if not requested_family:
        raise ValueError("family_id is required")
    repository = OfficialDocumentRepository(database)
    if current_version_id is None:
        current = repository.latest(requested_family)
        if current is None:
            raise ValueError(f"no official document version exists for family {requested_family}")
    else:
        current = repository.get(current_version_id)
        if current is None:
            raise ValueError(f"official document version {current_version_id} was not found")
        if current.family_id != requested_family:
            raise ValueError("requested current version does not belong to family_id")
    if current.predecessor_version_id is None:
        raise ValueError("current official document version has no predecessor to compare")
    previous = repository.get(current.predecessor_version_id)
    if previous is None:
        raise ValueError("current official document predecessor is missing from the repository")
    return extract_central_bank_stance(compare_document_versions(previous, current))


def _json_safe(value: object) -> object:
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, dict):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        return [_json_safe(item) for item in value]
    return value


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("document_database", type=Path)
    parser.add_argument("--family-id", required=True)
    parser.add_argument("--current-version-id", default=None)
    parser.add_argument("--output", type=Path, default=None)
    args = parser.parse_args()

    try:
        evidence = analyze_stance(
            args.document_database,
            family_id=args.family_id,
            current_version_id=args.current_version_id,
        )
    except ValueError as exc:
        raise SystemExit(str(exc)) from exc
    payload = _json_safe(asdict(evidence))
    text = json.dumps(payload, indent=2, sort_keys=True)
    if args.output is not None:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(text + "\n", encoding="utf-8")
    print(text)


if __name__ == "__main__":
    main()
