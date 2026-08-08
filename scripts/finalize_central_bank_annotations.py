"""Finalize blinded reviewer/adjudicator artifacts into semantic labels plus disagreement audit."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from forex_trader.infrastructure.official_document_repository import OfficialDocumentRepository
from forex_trader.research.stance_annotation_workflow import (
    FinalizedAnnotation,
    finalization_audit_to_dict,
    finalize_annotation_batch,
    load_adjudications,
    load_annotation_batch,
    load_reviewer_submissions,
    semantic_label_to_dict,
)


def finalize_annotation_files(
    document_database: Path,
    annotation_batch: Path,
    reviewer_submissions: Path,
    adjudications: Path,
) -> tuple[FinalizedAnnotation, ...]:
    batch = load_annotation_batch(annotation_batch)
    submissions = load_reviewer_submissions(reviewer_submissions)
    adjudication_records = load_adjudications(adjudications)
    repository = OfficialDocumentRepository(document_database)
    versions = repository.family_versions(batch.manifest.family_id)
    return finalize_annotation_batch(batch, submissions, adjudication_records, versions)


def _jsonl(records: list[dict[str, object]]) -> str:
    return "\n".join(json.dumps(item, sort_keys=True) for item in records) + "\n"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("document_database", type=Path)
    parser.add_argument("annotation_batch", type=Path)
    parser.add_argument("reviewer_submissions", type=Path)
    parser.add_argument("adjudications", type=Path)
    parser.add_argument("--labels-output", type=Path, required=True)
    parser.add_argument("--audit-output", type=Path, required=True)
    args = parser.parse_args()
    try:
        finalized = finalize_annotation_files(
            args.document_database,
            args.annotation_batch,
            args.reviewer_submissions,
            args.adjudications,
        )
    except (FileNotFoundError, ValueError) as exc:
        raise SystemExit(str(exc)) from exc
    args.labels_output.parent.mkdir(parents=True, exist_ok=True)
    args.audit_output.parent.mkdir(parents=True, exist_ok=True)
    args.labels_output.write_text(
        _jsonl([semantic_label_to_dict(item.semantic_label) for item in finalized]),
        encoding="utf-8",
    )
    args.audit_output.write_text(
        _jsonl([finalization_audit_to_dict(item.audit) for item in finalized]),
        encoding="utf-8",
    )
    print(len(finalized))


if __name__ == "__main__":
    main()
