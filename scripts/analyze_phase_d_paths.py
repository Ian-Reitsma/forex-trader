"""Analyze Phase-D entry/management policies on an immutable candle-path archive.

This command has no broker client and no credential path. Every policy is evaluated on the
same decision signals. Missed pending orders remain in the denominator with zero realized R.
A development period selects at most one predefined policy; an untouched chronological
holdout must independently confirm a positive paired lower confidence bound.
"""
from __future__ import annotations

import argparse
import json
from dataclasses import asdict
from datetime import datetime
from decimal import Decimal
from enum import Enum
from pathlib import Path

from forex_trader.research.evidence import load_decision_evidence
from forex_trader.research.management import HALF_AT_ONE_R_RUNNER, STRUCTURAL_SINGLE_TARGET
from forex_trader.research.order_types import OrderStyle
from forex_trader.research.path_dataset import build_phase_d_scenarios, load_candle_archive
from forex_trader.research.phase_d import (
    PhaseDPolicy,
    compare_phase_d_policies,
    recommend_phase_d_variant,
)


def _json_safe(value: object) -> object:
    if value is None:
        return None
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, Enum):
        return value.value
    if hasattr(value, "__dataclass_fields__"):
        return _json_safe(asdict(value))
    if isinstance(value, dict):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(item) for item in value]
    return value


def _policies(args: argparse.Namespace) -> tuple[PhaseDPolicy, tuple[PhaseDPolicy, ...]]:
    common = {
        "entry_slippage_pips": args.entry_slippage_pips,
        "exit_slippage_pips": args.exit_slippage_pips,
        "maximum_entry_bars": args.maximum_entry_bars,
        "maximum_holding_bars": args.maximum_holding_bars,
    }
    baseline = PhaseDPolicy(
        "market-structural",
        OrderStyle.MARKET,
        management=STRUCTURAL_SINGLE_TARGET,
        **common,
    )
    variants = (
        PhaseDPolicy("limit-0.25r-structural", OrderStyle.LIMIT, offset_r=Decimal("0.25"), management=STRUCTURAL_SINGLE_TARGET, **common),
        PhaseDPolicy("mit-0.25r-structural", OrderStyle.MARKET_IF_TOUCHED, offset_r=Decimal("0.25"), management=STRUCTURAL_SINGLE_TARGET, **common),
        PhaseDPolicy("stop-0.25r-structural", OrderStyle.STOP, offset_r=Decimal("0.25"), management=STRUCTURAL_SINGLE_TARGET, **common),
        PhaseDPolicy("market-half-1r-runner", OrderStyle.MARKET, management=HALF_AT_ONE_R_RUNNER, **common),
        PhaseDPolicy("limit-0.25r-half-1r-runner", OrderStyle.LIMIT, offset_r=Decimal("0.25"), management=HALF_AT_ONE_R_RUNNER, **common),
    )
    return baseline, variants


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("decision_evidence", type=Path)
    parser.add_argument("candle_archive", type=Path)
    parser.add_argument("--maximum-entry-bars", type=int, default=6)
    parser.add_argument("--maximum-holding-bars", type=int, default=24)
    parser.add_argument("--entry-slippage-pips", type=Decimal, default=Decimal("0.10"))
    parser.add_argument("--exit-slippage-pips", type=Decimal, default=Decimal("0.10"))
    parser.add_argument("--development-fraction", type=Decimal, default=Decimal("0.80"))
    parser.add_argument("--minimum-development-scenarios", type=int, default=100)
    parser.add_argument("--minimum-holdout-scenarios", type=int, default=30)
    parser.add_argument("--minimum-fill-rate", type=Decimal, default=Decimal("0.50"))
    parser.add_argument("--maximum-drawdown-ratio", type=Decimal, default=Decimal("1.10"))
    parser.add_argument("--bootstrap-iterations", type=int, default=4000)
    parser.add_argument("--bootstrap-seed", type=int, default=20260807)
    parser.add_argument("--output", type=Path, default=None)
    args = parser.parse_args()

    if args.maximum_entry_bars < 1 or args.maximum_holding_bars < 1:
        raise SystemExit("entry/holding bar horizons must be positive")
    if args.entry_slippage_pips < 0 or args.exit_slippage_pips < 0:
        raise SystemExit("slippage assumptions cannot be negative")
    if not Decimal("0") < args.development_fraction < Decimal("1"):
        raise SystemExit("--development-fraction must be in (0,1)")
    if args.minimum_development_scenarios < 2 or args.minimum_holdout_scenarios < 2:
        raise SystemExit("minimum scenario counts must be at least 2")
    if not Decimal("0") <= args.minimum_fill_rate <= Decimal("1"):
        raise SystemExit("--minimum-fill-rate must be in [0,1]")
    if args.maximum_drawdown_ratio <= 0:
        raise SystemExit("--maximum-drawdown-ratio must be positive")
    if args.bootstrap_iterations < 100:
        raise SystemExit("--bootstrap-iterations must be at least 100")

    decisions = tuple(
        item for item in load_decision_evidence(args.decision_evidence)
        if item.is_trade_candidate and item.signal_time is not None
    )
    if not decisions:
        raise SystemExit("decision evidence contains no trade candidates with signal time")
    fingerprints = {item.policy_fingerprint for item in decisions}
    if len(fingerprints) != 1:
        raise SystemExit("Phase-D comparison refuses mixed policy fingerprints")
    candle_archive = load_candle_archive(args.candle_archive)
    scenarios = build_phase_d_scenarios(
        decisions,
        candle_archive,
        maximum_entry_bars=args.maximum_entry_bars,
        maximum_holding_bars=args.maximum_holding_bars,
    )
    required_total = args.minimum_development_scenarios + args.minimum_holdout_scenarios
    if len(scenarios) < required_total:
        raise SystemExit(
            f"only {len(scenarios)} fully matured paired scenarios; need at least {required_total}. "
            "Collect more evidence instead of relaxing the comparison gate."
        )

    split_index = int(Decimal(len(scenarios)) * args.development_fraction)
    split_index = min(
        len(scenarios) - args.minimum_holdout_scenarios,
        max(args.minimum_development_scenarios, split_index),
    )
    development = scenarios[:split_index]
    holdout = scenarios[split_index:]
    baseline, variants = _policies(args)
    development_report = compare_phase_d_policies(
        development,
        baseline=baseline,
        variants=variants,
        bootstrap_iterations=args.bootstrap_iterations,
        bootstrap_seed=args.bootstrap_seed,
    )
    development_recommendation = recommend_phase_d_variant(
        development_report,
        minimum_scenarios=args.minimum_development_scenarios,
        minimum_fill_rate=args.minimum_fill_rate,
        maximum_drawdown_ratio=args.maximum_drawdown_ratio,
    )

    selected = None
    holdout_report = None
    holdout_recommendation = None
    if development_recommendation.eligible and development_recommendation.policy_name is not None:
        selected = next(item for item in variants if item.name == development_recommendation.policy_name)
        holdout_report = compare_phase_d_policies(
            holdout,
            baseline=baseline,
            variants=(selected,),
            bootstrap_iterations=args.bootstrap_iterations,
            bootstrap_seed=args.bootstrap_seed + 1,
        )
        holdout_recommendation = recommend_phase_d_variant(
            holdout_report,
            minimum_scenarios=args.minimum_holdout_scenarios,
            minimum_fill_rate=args.minimum_fill_rate,
            maximum_drawdown_ratio=args.maximum_drawdown_ratio,
        )

    confirmed = bool(
        selected is not None
        and development_recommendation.eligible
        and holdout_recommendation is not None
        and holdout_recommendation.eligible
    )
    payload = {
        "research_only": True,
        "broker_client_present": False,
        "practice_authority_changed": False,
        "policy_fingerprint": next(iter(fingerprints)),
        "matured_scenarios": len(scenarios),
        "development_scenarios": len(development),
        "untouched_holdout_scenarios": len(holdout),
        "baseline": baseline.name,
        "candidate_policies": [item.name for item in variants],
        "development": _json_safe(development_report),
        "development_recommendation": _json_safe(development_recommendation),
        "holdout": _json_safe(holdout_report),
        "holdout_recommendation": _json_safe(holdout_recommendation),
        "confirmed_research_candidate": selected.name if confirmed and selected is not None else None,
        "interpretation": (
            "A confirmed research candidate improved paired lower-bound R on both development and untouched holdout paths. "
            "It still has no Practice authority; live broker mapping, execution evidence, calibration, drawdown, ablation and policy review remain separate gates."
        ),
    }
    text = json.dumps(payload, indent=2, sort_keys=True)
    if args.output is not None:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(text + "\n", encoding="utf-8")
    print(text)


if __name__ == "__main__":
    main()
