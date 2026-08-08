"""Create a sealed chronological calibration/holdout split from a frozen annotation batch."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from forex_trader.research.stance_annotation_workflow import annotation_batch_to_dict, load_annotation_batch
from forex_trader.research.stance_semantic_holdout import (
    SemanticPartition,
    build_partition_annotation_batch,
    build_semantic_holdout_manifest,
    semantic_holdout_manifest_to_dict,
)


def create_semantic_holdout_files(
    annotation_batch: Path,
) -> tuple[dict[str, object], dict[str, object], dict[str, object]]:
    batch = load_annotation_batch(annotation_batch)
    manifest = build_semantic_holdout_manifest(batch)
    calibration = build_partition_annotation_batch(batch, manifest, SemanticPartition.CALIBRATION)
    holdout = build_partition_annotation_batch(batch, manifest, SemanticPartition.HOLDOUT)
    return (
        semantic_holdout_manifest_to_dict(manifest),
        annotation_batch_to_dict(calibration),
        annotation_batch_to_dict(holdout),
    )


def _write_json(path: Path, payload: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("annotation_batch", type=Path)
    parser.add_argument("--manifest-output", type=Path, required=True)
    parser.add_argument("--calibration-output", type=Path, required=True)
    parser.add_argument("--holdout-output", type=Path, required=True)
    args = parser.parse_args()
    try:
        manifest, calibration, holdout = create_semantic_holdout_files(args.annotation_batch)
    except (FileNotFoundError, ValueError) as exc:
        raise SystemExit(str(exc)) from exc
    _write_json(args.manifest_output, manifest)
    _write_json(args.calibration_output, calibration)
    _write_json(args.holdout_output, holdout)
    print(manifest["manifest_id"])


if __name__ == "__main__":
    main()
