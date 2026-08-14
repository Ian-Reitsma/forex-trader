"""Build an episode-aware paired-ablation report from frozen research evidence.

This script is read-only with respect to broker/runtime state. It never submits, modifies,
or closes orders. The statistical unit is the first chronological observation of each
structurally identifiable setup episode; later snapshots are retained in the raw evidence
but cannot replace an incomplete or unfavorable first observation.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from forex_trader.research.ablations import (
    load_ablation_decisions,
    load_matured_ablation_outcomes,
)
from forex_trader.research.episode_ablations import (
    build_episode_ablation_report,
    report_to_jsonable,
)
from forex_trader.research.evidence import load_decision_evidence


parser = argparse.ArgumentParser()
parser.add_argument("decision_evidence", type=Path)
parser.add_argument("ablation_decisions", type=Path)
parser.add_argument("matured_outcomes", type=Path)
parser.add_argument("--output", type=Path)
args = parser.parse_args()

report = build_episode_ablation_report(
    load_decision_evidence(args.decision_evidence),
    load_ablation_decisions(args.ablation_decisions, require_complete=False),
    load_matured_ablation_outcomes(args.matured_outcomes),
)
payload = report_to_jsonable(report)
rendered = json.dumps(payload, indent=2, sort_keys=True) + "\n"
if args.output is not None:
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(rendered, encoding="utf-8")
print(rendered, end="")
