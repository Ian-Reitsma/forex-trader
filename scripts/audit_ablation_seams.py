"""Locate production decision functions that consume each ablation component.

This is a deterministic static-analysis aid, not an authority mechanism. It deliberately
excludes `research/` so research scaffolding cannot satisfy the seam audit itself.
"""
from __future__ import annotations

import argparse
import json
from dataclasses import asdict
from pathlib import Path

from forex_trader.research.seam_audit import assert_required_seams, audit_production_seams, top_seams


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--source-root",
        type=Path,
        default=Path("src/forex_trader"),
        help="Production package root to audit",
    )
    parser.add_argument("--per-component", type=int, default=8)
    parser.add_argument("--output", type=Path, default=None)
    args = parser.parse_args()

    candidates = audit_production_seams(args.source_root)
    assert_required_seams(candidates)
    grouped = top_seams(candidates, per_component=args.per_component)
    payload = {
        "research_only": True,
        "execution_authority": False,
        "source_root": str(args.source_root),
        "components": {
            component: [asdict(item) for item in values]
            for component, values in grouped.items()
        },
    }
    text = json.dumps(payload, indent=2, sort_keys=True)
    if args.output is not None:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(text + "\n", encoding="utf-8")
    print(text)


if __name__ == "__main__":
    main()
