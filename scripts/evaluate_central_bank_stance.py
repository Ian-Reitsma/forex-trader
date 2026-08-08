"""Evaluate research-only stance rules against immutable human-reviewed labels."""
from __future__ import annotations

import argparse
import json
from dataclasses import asdict
from decimal import Decimal
from enum import Enum
from pathlib import Path

from forex_trader.infrastructure.official_document_repository import OfficialDocumentRepository
from forex_trader.research.central_bank_stance_baselines import trivial_stance_baselines
from forex_trader.research.central_bank_stance_evaluation import evaluate_stance_dataset, load_stance_labels


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
    parser.add_argument("labels_jsonl", type=Path)
    parser.add_argument("--output", type=Path, default=None)
    args = parser.parse_args()

    try:
        dataset = load_stance_labels(str(args.labels_jsonl))
        report = evaluate_stance_dataset(dataset, OfficialDocumentRepository(args.document_database))
        baselines = trivial_stance_baselines(dataset)
    except ValueError as exc:
        raise SystemExit(str(exc)) from exc

    payload = {
        "research_only": True,
        "execution_authority": False,
        "dataset_id": dataset.dataset_id,
        "report": _json_safe(asdict(report)),
        "baselines": _json_safe([asdict(item) for item in baselines]),
        "interpretation": (
            "This evaluates source-backed stance evidence against immutable human-reviewed labels. "
            "It does not grant runtime or execution authority."
        ),
    }
    text = json.dumps(payload, indent=2, sort_keys=True)
    if args.output is not None:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(text + "\n", encoding="utf-8")
    print(text)


if __name__ == "__main__":
    main()
