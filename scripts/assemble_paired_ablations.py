"""Assemble promotion-compatible paired ablation evidence from matured variant outcomes.

This command is offline/research-only. It has no broker client and cannot grant execution
authority. The caller supplies the primary research dataset ID; every variant must be present
for every snapshot before any component expectancy is emitted.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from forex_trader.research.ablations import (
    load_matured_ablation_outcomes,
    paired_ablation_evidence,
    paired_artifact_id,
    write_paired_ablation_evidence,
)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("matured_outcomes", type=Path)
    parser.add_argument("--primary-dataset-id", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    outcomes = load_matured_ablation_outcomes(args.matured_outcomes)
    evidence = paired_ablation_evidence(
        outcomes,
        primary_dataset_id=args.primary_dataset_id,
    )
    artifact_id = paired_artifact_id(outcomes)
    write_paired_ablation_evidence(args.output, evidence, artifact_id=artifact_id)
    payload = {
        "research_only": True,
        "execution_authority": False,
        "practice_authority_changed": False,
        "primary_dataset_id": args.primary_dataset_id,
        "paired_artifact_id": artifact_id,
        "paired_snapshots": evidence[0].sample_size if evidence else 0,
        "output": str(args.output),
    }
    print(json.dumps(payload, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
