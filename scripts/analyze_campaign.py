"""Analyze campaign-evidence JSONL and diagnose the dominant operational bottleneck."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from forex_trader.research.campaign_analysis import analyze_campaign_file

parser = argparse.ArgumentParser()
parser.add_argument("evidence", type=Path, nargs="?", default=Path("campaign-evidence.jsonl"))
parser.add_argument("--minimum-cycles", type=int, default=5)
parser.add_argument("--minimum-evaluations", type=int, default=100)
parser.add_argument(
    "--policy-fingerprint",
    default=None,
    help="Select one policy cohort when the evidence file contains multiple fingerprints",
)
args = parser.parse_args()

if args.minimum_cycles < 1:
    raise SystemExit("--minimum-cycles must be positive")
if args.minimum_evaluations < 1:
    raise SystemExit("--minimum-evaluations must be positive")

try:
    diagnosis = analyze_campaign_file(
        args.evidence,
        minimum_cycles=args.minimum_cycles,
        minimum_evaluations=args.minimum_evaluations,
        policy_fingerprint=args.policy_fingerprint,
    )
except (FileNotFoundError, ValueError) as exc:
    raise SystemExit(str(exc)) from exc

print(json.dumps(diagnosis.to_jsonable(), indent=2, sort_keys=True))
