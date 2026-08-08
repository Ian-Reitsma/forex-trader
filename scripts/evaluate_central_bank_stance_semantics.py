"""Evaluate source-backed stance extraction against an imported human-reviewed label corpus."""
from __future__ import annotations

import argparse
import json
from dataclasses import asdict
from datetime import datetime
from decimal import Decimal
from enum import Enum
from pathlib import Path

from forex_trader.infrastructure.official_document_repository import OfficialDocumentRepository
from forex_trader.intelligence.official_documents import OfficialDocumentVersion
from forex_trader.research.stance_semantic_validation import (
    SemanticEvaluationReport,
    evaluate_semantic_labels,
    load_semantic_label_corpus,
)


def evaluate_semantic_corpus(
    document_database: Path,
    label_corpus: Path,
) -> SemanticEvaluationReport:
    labels = load_semantic_label_corpus(label_corpus)
    repository = OfficialDocumentRepository(document_database)
    versions: dict[str, OfficialDocumentVersion] = {}
    for label in labels:
        for version_id in (label.previous_version_id, label.current_version_id):
            if version_id in versions:
                continue
            version = repository.get(version_id)
            if version is None:
                raise ValueError(f"semantic label references missing document version {version_id}")
            versions[version_id] = version
    return evaluate_semantic_labels(labels, versions.values())


def _json_safe(value: object) -> object:
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, datetime):
        return value.isoformat()
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
    parser.add_argument("label_corpus", type=Path)
    parser.add_argument("--output", type=Path, default=None)
    args = parser.parse_args()
    try:
        report = evaluate_semantic_corpus(args.document_database, args.label_corpus)
    except (FileNotFoundError, ValueError) as exc:
        raise SystemExit(str(exc)) from exc
    text = json.dumps(_json_safe(asdict(report)), indent=2, sort_keys=True)
    if args.output is not None:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(text + "\n", encoding="utf-8")
    print(text)


if __name__ == "__main__":
    main()
