"""Create one immutable reviewer submission from a model-blinded annotation packet."""
from __future__ import annotations

import argparse
import json
from datetime import datetime
from pathlib import Path

from forex_trader.research.central_bank_stance import EvidenceDisposition, PolicyDimension, StanceDirection
from forex_trader.research.stance_annotation_workflow import (
    ReviewerSubmission,
    load_annotation_batch,
    reviewer_submission_to_dict,
)
from forex_trader.research.stance_semantic_validation import DimensionSemanticLabel


def _parse_time(value: str) -> datetime:
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None:
        raise ValueError("submission time must be timezone-aware")
    return parsed


def _parse_dimension(value: str) -> DimensionSemanticLabel:
    parts = value.split(":")
    if len(parts) != 3:
        raise ValueError("dimension must use dimension:direction:disposition")
    try:
        return DimensionSemanticLabel(
            dimension=PolicyDimension(parts[0]),
            direction=StanceDirection(parts[1]),
            disposition=EvidenceDisposition(parts[2]),
        )
    except ValueError as exc:
        raise ValueError(f"invalid dimension label {value}") from exc


def create_review_submission(
    batch_path: Path,
    *,
    packet_id: str,
    reviewer_id: str,
    submitted_at: datetime,
    direction: StanceDirection,
    disposition: EvidenceDisposition,
    dimensions: tuple[DimensionSemanticLabel, ...] = (),
) -> ReviewerSubmission:
    batch = load_annotation_batch(batch_path)
    matches = tuple(item for item in batch.packets if item.packet_id == packet_id)
    if len(matches) != 1:
        raise ValueError("packet_id must identify exactly one packet in the frozen annotation batch")
    return ReviewerSubmission.create(
        matches[0],
        reviewer_id=reviewer_id,
        submitted_at=submitted_at,
        direction=direction,
        disposition=disposition,
        dimensions=dimensions,
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("annotation_batch", type=Path)
    parser.add_argument("--packet-id", required=True)
    parser.add_argument("--reviewer-id", required=True)
    parser.add_argument("--submitted-at", required=True)
    parser.add_argument("--direction", required=True, choices=[item.value for item in StanceDirection])
    parser.add_argument("--disposition", required=True, choices=[item.value for item in EvidenceDisposition])
    parser.add_argument(
        "--dimension",
        action="append",
        default=[],
        help="optional dimension:direction:disposition; repeat for multiple dimensions",
    )
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    try:
        submission = create_review_submission(
            args.annotation_batch,
            packet_id=args.packet_id,
            reviewer_id=args.reviewer_id,
            submitted_at=_parse_time(args.submitted_at),
            direction=StanceDirection(args.direction),
            disposition=EvidenceDisposition(args.disposition),
            dimensions=tuple(_parse_dimension(value) for value in args.dimension),
        )
    except (FileNotFoundError, ValueError) as exc:
        raise SystemExit(str(exc)) from exc
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(reviewer_submission_to_dict(submission), sort_keys=True) + "\n", encoding="utf-8")
    print(submission.submission_id)


if __name__ == "__main__":
    main()
