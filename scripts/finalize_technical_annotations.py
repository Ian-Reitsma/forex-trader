from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

from forex_trader.research.technical_annotation import (
    BinaryTechnicalLabel,
    TechnicalAdjudication,
    TechnicalDirectionLabel,
    TechnicalGroundTruthLabel,
    TechnicalReviewerSubmission,
    finalize_technical_labels,
    label_payload,
    technical_batch_from_payload,
)


def _json_lines(path: Path | None) -> list[dict[str, object]]:
    if path is None:
        return []
    rows: list[dict[str, object]] = []
    for line_number, raw in enumerate(path.read_text().splitlines(), start=1):
        line = raw.strip()
        if not line:
            continue
        payload = json.loads(line)
        if not isinstance(payload, dict):
            raise ValueError(f"{path}: line {line_number} must be a JSON object")
        rows.append(payload)
    return rows


def _label(payload: object) -> TechnicalGroundTruthLabel:
    if not isinstance(payload, dict):
        raise ValueError("technical label must be an object")
    expected = {"zone", "liquidity_sweep", "structure_shift", "retest", "direction"}
    if set(payload) != expected:
        raise ValueError("technical label must contain exactly zone/liquidity_sweep/structure_shift/retest/direction")
    return TechnicalGroundTruthLabel(
        zone=BinaryTechnicalLabel(str(payload["zone"])),
        liquidity_sweep=BinaryTechnicalLabel(str(payload["liquidity_sweep"])),
        structure_shift=BinaryTechnicalLabel(str(payload["structure_shift"])),
        retest=BinaryTechnicalLabel(str(payload["retest"])),
        direction=TechnicalDirectionLabel(str(payload["direction"])),
    )


def _verify_manifest(payload: object, *, batch_id: str, policy_version: str, frozen_as_of: str) -> dict[str, object]:
    if not isinstance(payload, dict):
        raise ValueError("technical holdout manifest must be an object")
    if payload.get("batch_id") != batch_id or payload.get("policy_version") != policy_version:
        raise ValueError("technical holdout manifest identity does not match annotation batch")
    if payload.get("frozen_as_of") != frozen_as_of:
        raise ValueError("technical holdout manifest frozen_as_of does not match annotation batch")
    calibration = payload.get("calibration_packet_ids")
    holdout = payload.get("holdout_packet_ids")
    if not isinstance(calibration, list) or not isinstance(holdout, list):
        raise ValueError("technical holdout manifest partitions must be lists")
    canonical = {
        "batch_id": batch_id,
        "policy_version": policy_version,
        "frozen_as_of": frozen_as_of,
        "calibration_packet_ids": tuple(str(item) for item in calibration),
        "holdout_packet_ids": tuple(str(item) for item in holdout),
    }
    digest = hashlib.sha256(
        json.dumps(canonical, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    if digest != payload.get("manifest_hash"):
        raise ValueError("technical holdout manifest hash mismatch")
    return payload


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Finalize independently reviewed technical labels for one frozen calibration/holdout partition."
    )
    parser.add_argument("batch", type=Path)
    parser.add_argument("manifest", type=Path)
    parser.add_argument("reviewer_submissions", type=Path, help="JSONL independent reviewer labels")
    parser.add_argument("--adjudications", type=Path, default=None, help="JSONL independent adjudications")
    parser.add_argument("--partition", choices=("calibration", "holdout"), required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    batch_payload = json.loads(args.batch.read_text())
    if not isinstance(batch_payload, dict):
        raise ValueError("technical annotation batch must be a JSON object")
    batch = technical_batch_from_payload(batch_payload)
    manifest_payload = _verify_manifest(
        json.loads(args.manifest.read_text()),
        batch_id=batch.batch_id,
        policy_version=batch.policy_version,
        frozen_as_of=batch.frozen_as_of.isoformat(),
    )
    key = "calibration_packet_ids" if args.partition == "calibration" else "holdout_packet_ids"
    required = tuple(str(item) for item in manifest_payload[key])  # type: ignore[index]

    submissions = tuple(
        TechnicalReviewerSubmission(
            packet_id=str(row["packet_id"]),
            reviewer_id=str(row["reviewer_id"]),
            label=_label(row["label"]),
        )
        for row in _json_lines(args.reviewer_submissions)
    )
    adjudications = tuple(
        TechnicalAdjudication(
            packet_id=str(row["packet_id"]),
            adjudicator_id=str(row["adjudicator_id"]),
            label=_label(row["label"]),
        )
        for row in _json_lines(args.adjudications)
    )
    corpus = finalize_technical_labels(
        batch,
        submissions,
        adjudications,
        required_packet_ids=required,
    )
    rows = [
        {
            "schema_version": "1.0",
            "batch_id": corpus.batch_id,
            "policy_version": corpus.policy_version,
            "partition": args.partition,
            "packet_id": item.packet_id,
            "label": label_payload(item.label),
            "reviewer_ids": list(item.reviewer_ids),
            "agreement": item.agreement,
            "adjudicator_id": item.adjudicator_id,
        }
        for item in corpus.labels
    ]
    args.output.write_text("".join(json.dumps(row, sort_keys=True) + "\n" for row in rows))


if __name__ == "__main__":
    main()
