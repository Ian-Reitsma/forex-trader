"""Export a frozen source-only central-bank annotation batch for independent human review."""
from __future__ import annotations

import argparse
import json
from datetime import datetime
from pathlib import Path

from forex_trader.infrastructure.official_document_repository import OfficialDocumentRepository
from forex_trader.research.stance_annotation_workflow import (
    AnnotationBatch,
    annotation_batch_to_dict,
    build_blinded_annotation_batch,
)


def export_annotation_batch(
    document_database: Path,
    *,
    family_id: str,
    annotation_policy_version: str,
    as_of: datetime,
) -> AnnotationBatch:
    if as_of.tzinfo is None:
        raise ValueError("annotation batch as_of must be timezone-aware")
    requested_family = family_id.strip()
    if not requested_family:
        raise ValueError("family_id is required")
    policy = annotation_policy_version.strip()
    if not policy:
        raise ValueError("annotation_policy_version is required")
    repository = OfficialDocumentRepository(document_database)
    versions = repository.family_versions(requested_family)
    if len(versions) < 2:
        raise ValueError(f"family {requested_family} requires at least two persisted document versions")
    return build_blinded_annotation_batch(
        versions,
        annotation_policy_version=policy,
        as_of=as_of,
    )


def _parse_as_of(value: str) -> datetime:
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None:
        raise ValueError("as_of must be timezone-aware")
    return parsed


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("document_database", type=Path)
    parser.add_argument("--family-id", required=True)
    parser.add_argument("--annotation-policy-version", required=True)
    parser.add_argument(
        "--as-of",
        required=True,
        help="timezone-aware frozen corpus cutoff; every comparable family version available by this instant is exported",
    )
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    try:
        batch = export_annotation_batch(
            args.document_database,
            family_id=args.family_id,
            annotation_policy_version=args.annotation_policy_version,
            as_of=_parse_as_of(args.as_of),
        )
    except (FileNotFoundError, ValueError) as exc:
        raise SystemExit(str(exc)) from exc
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(annotation_batch_to_dict(batch), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(batch.manifest.batch_id)


if __name__ == "__main__":
    main()
