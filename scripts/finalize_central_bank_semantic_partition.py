"""Finalize one sealed semantic partition after reconstructing the complete official-document source batch."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from forex_trader.infrastructure.official_document_repository import OfficialDocumentRepository
from forex_trader.research.stance_annotation_workflow import (
    load_adjudications,
    load_annotation_batch,
    load_reviewer_submissions,
    semantic_label_to_dict,
)
from forex_trader.research.stance_semantic_holdout import (
    FinalizedPartitionAnnotation,
    SemanticPartition,
    finalize_semantic_partition,
    load_semantic_holdout_manifest,
    partition_finalization_audit_to_dict,
)


def finalize_semantic_partition_files(
    document_database: Path,
    source_annotation_batch: Path,
    holdout_manifest: Path,
    partition_annotation_batch: Path,
    reviewer_submissions: Path,
    adjudications: Path,
    *,
    partition: SemanticPartition,
) -> tuple[FinalizedPartitionAnnotation, ...]:
    source_batch = load_annotation_batch(source_annotation_batch)
    manifest = load_semantic_holdout_manifest(holdout_manifest)
    partition_batch = load_annotation_batch(partition_annotation_batch)
    submissions = load_reviewer_submissions(reviewer_submissions)
    adjudication_records = load_adjudications(adjudications)
    repository = OfficialDocumentRepository(document_database)
    versions = repository.family_versions(source_batch.manifest.family_id)
    return finalize_semantic_partition(
        source_batch,
        manifest,
        partition_batch,
        partition,
        submissions,
        adjudication_records,
        versions,
    )


def _jsonl(records: list[dict[str, object]]) -> str:
    return "\n".join(json.dumps(item, sort_keys=True) for item in records) + "\n"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("document_database", type=Path)
    parser.add_argument("source_annotation_batch", type=Path)
    parser.add_argument("holdout_manifest", type=Path)
    parser.add_argument("partition_annotation_batch", type=Path)
    parser.add_argument("reviewer_submissions", type=Path)
    parser.add_argument("adjudications", type=Path)
    parser.add_argument("--partition", required=True, choices=[item.value for item in SemanticPartition])
    parser.add_argument("--labels-output", type=Path, required=True)
    parser.add_argument("--audit-output", type=Path, required=True)
    args = parser.parse_args()
    try:
        finalized = finalize_semantic_partition_files(
            args.document_database,
            args.source_annotation_batch,
            args.holdout_manifest,
            args.partition_annotation_batch,
            args.reviewer_submissions,
            args.adjudications,
            partition=SemanticPartition(args.partition),
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
        _jsonl([partition_finalization_audit_to_dict(item.audit) for item in finalized]),
        encoding="utf-8",
    )
    print(len(finalized))


if __name__ == "__main__":
    main()
