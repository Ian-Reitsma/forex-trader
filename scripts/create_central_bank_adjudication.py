"""Create one adjudication using every reviewer submission for a blinded packet."""
from __future__ import annotations

import argparse
import json
from datetime import datetime
from pathlib import Path

from forex_trader.research.central_bank_stance import EvidenceDisposition, PolicyDimension, StanceDirection
from forex_trader.research.stance_annotation_workflow import (
    AdjudicationRecord,
    adjudication_to_dict,
    load_annotation_batch,
    load_reviewer_submissions,
)
from forex_trader.research.stance_semantic_validation import DimensionSemanticLabel


def _parse_time(value: str) -> datetime:
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None:
        raise ValueError("adjudication time must be timezone-aware")
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


def create_adjudication(
    batch_path: Path,
    submissions_path: Path,
    *,
    packet_id: str,
    adjudicator_id: str,
    adjudicated_at: datetime,
    direction: StanceDirection,
    disposition: EvidenceDisposition,
    dimensions: tuple[DimensionSemanticLabel, ...] = (),
) -> AdjudicationRecord:
    batch = load_annotation_batch(batch_path)
    matches = tuple(item for item in batch.packets if item.packet_id == packet_id)
    if len(matches) != 1:
        raise ValueError("packet_id must identify exactly one packet in the frozen annotation batch")
    submissions = tuple(
        item for item in load_reviewer_submissions(submissions_path) if item.packet_id == packet_id
    )
    return AdjudicationRecord.create(
        matches[0],
        submissions,
        adjudicator_id=adjudicator_id,
        adjudicated_at=adjudicated_at,
        direction=direction,
        disposition=disposition,
        dimensions=dimensions,
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("annotation_batch", type=Path)
    parser.add_argument("reviewer_submissions", type=Path)
    parser.add_argument("--packet-id", required=True)
    parser.add_argument("--adjudicator-id", required=True)
    parser.add_argument("--adjudicated-at", required=True)
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
        adjudication = create_adjudication(
            args.annotation_batch,
            args.reviewer_submissions,
            packet_id=args.packet_id,
            adjudicator_id=args.adjudicator_id,
            adjudicated_at=_parse_time(args.adjudicated_at),
            direction=StanceDirection(args.direction),
            disposition=EvidenceDisposition(args.disposition),
            dimensions=tuple(_parse_dimension(value) for value in args.dimension),
        )
    except (FileNotFoundError, ValueError) as exc:
        raise SystemExit(str(exc)) from exc
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(adjudication_to_dict(adjudication), sort_keys=True) + "\n", encoding="utf-8")
    print(adjudication.adjudication_id)


if __name__ == "__main__":
    main()
