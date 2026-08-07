"""Assemble promotion-compatible paired ablation evidence from matured variant outcomes.

This command is offline/research-only. It has no broker client and cannot grant execution
authority. Every variant must be present for every snapshot before component expectancy and
paired bootstrap uncertainty are emitted.
"""
from __future__ import annotations

import argparse
import json
from decimal import Decimal
from pathlib import Path

from forex_trader.research.ablation_uncertainty import (
    paired_ablation_uncertainty_evidence,
    write_paired_ablation_uncertainty_evidence,
)
from forex_trader.research.ablations import load_matured_ablation_outcomes, paired_artifact_id


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("matured_outcomes", type=Path)
    parser.add_argument("--primary-dataset-id", required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--confidence", type=Decimal, default=Decimal("0.90"))
    parser.add_argument("--bootstrap-iterations", type=int, default=2000)
    parser.add_argument("--bootstrap-seed", type=int, default=20260807)
    args = parser.parse_args()

    outcomes = load_matured_ablation_outcomes(args.matured_outcomes)
    evidence = paired_ablation_uncertainty_evidence(
        outcomes,
        primary_dataset_id=args.primary_dataset_id,
        confidence=args.confidence,
        bootstrap_iterations=args.bootstrap_iterations,
        bootstrap_seed=args.bootstrap_seed,
    )
    artifact_id = paired_artifact_id(outcomes)
    write_paired_ablation_uncertainty_evidence(args.output, evidence, artifact_id=artifact_id)
    payload = {
        "research_only": True,
        "execution_authority": False,
        "practice_authority_changed": False,
        "primary_dataset_id": args.primary_dataset_id,
        "paired_artifact_id": artifact_id,
        "paired_snapshots": evidence[0].sample_size if evidence else 0,
        "confidence": str(args.confidence),
        "bootstrap_iterations": args.bootstrap_iterations,
        "bootstrap_seed": args.bootstrap_seed,
        "output": str(args.output),
    }
    print(json.dumps(payload, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
