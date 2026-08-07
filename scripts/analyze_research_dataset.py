"""Analyze labeled decision evidence without granting execution authority.

The analyzer enforces chronological train/validation/test separation, measures target-event
calibration on validation data, refits empirical cohort history through validation, and then
applies a conservative after-cost EV gate to the untouched test fold. Output is research
evidence only; it cannot promote a policy or authorize a broker order.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from decimal import Decimal
from pathlib import Path

from forex_trader.research.advanced import PredictionObservation, calibration_report
from forex_trader.research.backtest import OutcomeStatus, summarize_trades
from forex_trader.research.cohorts import HierarchicalOutcomeModel, ResearchExpectedValueGate, chronological_split
from forex_trader.research.dataset import (
    join_labeled_decisions,
    load_outcome_evidence,
    reward_r_from_geometry,
    spread_cost_r_from_quote,
)
from forex_trader.research.evidence import load_decision_evidence


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


parser = argparse.ArgumentParser()
parser.add_argument("decision_evidence", type=Path)
parser.add_argument("outcome_evidence", type=Path)
parser.add_argument("--setup-family", default=None, help="Analyze exactly one setup family; required for setup promotion evidence")
parser.add_argument("--minimum-labeled-trades", type=int, default=200)
parser.add_argument("--minimum-cohort-trades", type=int, default=30)
parser.add_argument("--minimum-ev-sample", type=int, default=50)
parser.add_argument("--maximum-confidence-half-width", type=Decimal, default=Decimal("0.20"))
parser.add_argument("--maximum-calibration-error", type=Decimal, default=Decimal("0.08"))
parser.add_argument("--minimum-expected-net-r", type=Decimal, default=Decimal("0"))
parser.add_argument("--minimum-conservative-net-r", type=Decimal, default=Decimal("0"))
parser.add_argument("--adverse-selection-r", type=Decimal, default=Decimal("0.03"))
parser.add_argument("--operational-uncertainty-r", type=Decimal, default=Decimal("0.05"))
parser.add_argument("--include-instrument-cohort", action="store_true")
parser.add_argument("--output", type=Path, default=None, help="Optional immutable research-report JSON output")
args = parser.parse_args()

if args.minimum_labeled_trades < 3:
    raise SystemExit("--minimum-labeled-trades must be at least 3")
if args.minimum_cohort_trades < 2 or args.minimum_ev_sample < 2:
    raise SystemExit("cohort/EV sample requirements must be at least 2")
if args.adverse_selection_r < 0 or args.operational_uncertainty_r < 0:
    raise SystemExit("uncertainty costs cannot be negative")

decision_sha256 = _sha256(args.decision_evidence)
outcome_sha256 = _sha256(args.outcome_evidence)
dataset_id = hashlib.sha256(f"{decision_sha256}:{outcome_sha256}".encode()).hexdigest()
decisions = load_decision_evidence(args.decision_evidence)
outcomes = load_outcome_evidence(args.outcome_evidence)
labeled = join_labeled_decisions(decisions, outcomes)
if args.setup_family is not None:
    requested_setup = args.setup_family.strip()
    if not requested_setup:
        raise SystemExit("--setup-family cannot be empty")
    labeled = tuple(item for item in labeled if item.decision.setup_family == requested_setup)
else:
    requested_setup = None
setup_families = sorted({item.decision.setup_family or "unknown" for item in labeled})
if not labeled:
    raise SystemExit("research dataset has no labeled trades for the requested setup family")
if len(labeled) < args.minimum_labeled_trades:
    scope = f" for setup_family={requested_setup}" if requested_setup is not None else ""
    raise SystemExit(
        f"research dataset has {len(labeled)} labeled trades{scope}; "
        f"minimum is {args.minimum_labeled_trades}. Collect more point-in-time evidence rather than weakening gates."
    )
policy_fingerprints = {item.decision.policy_fingerprint for item in labeled}
if len(policy_fingerprints) != 1:
    raise SystemExit(
        "research dataset mixes policy fingerprints; analyze one immutable strategy/policy cohort at a time"
    )

split = chronological_split(labeled)
train_model = HierarchicalOutcomeModel(
    split.train,
    minimum_cohort_trades=args.minimum_cohort_trades,
    include_instrument=args.include_instrument_cohort,
)
validation_observations = []
validation_cohorts: dict[str, int] = {}
for row in split.validation:
    estimate = train_model.estimate(row.decision)
    validation_cohorts[estimate.cohort] = validation_cohorts.get(estimate.cohort, 0) + 1
    validation_observations.append(
        PredictionObservation(
            probability=estimate.estimate.p_target_before_stop,
            outcome=row.outcome.status is OutcomeStatus.WIN,
            cohort=estimate.cohort,
        )
    )
validation_calibration = calibration_report(validation_observations)

history = (*split.train, *split.validation)
final_model = HierarchicalOutcomeModel(
    history,
    minimum_cohort_trades=args.minimum_cohort_trades,
    include_instrument=args.include_instrument_cohort,
)
average_execution_cost_r = (
    sum((row.outcome.estimated_cost_r for row in history), Decimal("0")) / Decimal(len(history))
)
gate = ResearchExpectedValueGate(
    minimum_sample_size=args.minimum_ev_sample,
    maximum_confidence_half_width=args.maximum_confidence_half_width,
    maximum_calibration_error=args.maximum_calibration_error,
    minimum_expected_net_r=args.minimum_expected_net_r,
    minimum_conservative_net_r=args.minimum_conservative_net_r,
)

test_decisions = []
eligible_outcomes = []
for row in split.test:
    estimate = final_model.estimate(row.decision)
    gate_result = gate.evaluate(
        estimate,
        expected_gain_r=reward_r_from_geometry(row.decision),
        spread_cost_r=spread_cost_r_from_quote(row.decision),
        slippage_cost_r=average_execution_cost_r,
        adverse_selection_r=args.adverse_selection_r,
        operational_uncertainty_r=args.operational_uncertainty_r,
        calibration_error=validation_calibration.expected_calibration_error,
    )
    if gate_result.eligible:
        eligible_outcomes.append(row.outcome)
    test_decisions.append(
        {
            "signal_time": row.decision.signal_time.isoformat() if row.decision.signal_time else None,
            "instrument": row.decision.instrument,
            "setup_family": row.decision.setup_family,
            "regime": row.decision.regime,
            "session_phase": row.decision.session_phase,
            "cohort": gate_result.cohort,
            "eligible": gate_result.eligible,
            "expected_net_r": str(gate_result.expected_net_r),
            "conservative_net_r": str(gate_result.conservative_net_r),
            "p_target": str(gate_result.probability_target),
            "p_target_lower": str(gate_result.probability_target_lower),
            "p_stop": str(gate_result.probability_stop),
            "p_timeout": str(gate_result.probability_timeout),
            "expected_timeout_r": str(gate_result.expected_timeout_r),
            "sample_size": gate_result.sample_size,
            "confidence_half_width": str(gate_result.confidence_half_width),
            "actual_status": row.outcome.status.value,
            "actual_r": str(row.outcome.r_multiple),
            "reasons": list(gate_result.reasons),
        }
    )

all_test = summarize_trades([row.outcome for row in split.test])
eligible_test = summarize_trades(eligible_outcomes) if eligible_outcomes else None
report = {
    "research_only": True,
    "execution_authority": False,
    "policy_fingerprint": next(iter(policy_fingerprints)),
    "setup_family_filter": requested_setup,
    "setup_families_observed": setup_families,
    "dataset": {
        "dataset_id": dataset_id,
        "decision_sha256": decision_sha256,
        "outcome_sha256": outcome_sha256,
        "labeled_trades": len(labeled),
        "train": len(split.train),
        "validation": len(split.validation),
        "test": len(split.test),
    },
    "model": {
        "cohort_hierarchy": (
            "setup+regime+session+instrument -> setup+regime+session -> setup+regime -> setup -> all"
            if args.include_instrument_cohort
            else "setup+regime+session -> setup+regime -> setup -> all"
        ),
        "minimum_cohort_trades": args.minimum_cohort_trades,
        "average_historical_execution_cost_r": str(average_execution_cost_r),
    },
    "validation_calibration": {
        "count": validation_calibration.count,
        "brier_score": str(validation_calibration.brier_score),
        "expected_calibration_error": str(validation_calibration.expected_calibration_error),
        "cohorts": dict(sorted(validation_cohorts.items())),
    },
    "ev_gate": {
        "minimum_sample": args.minimum_ev_sample,
        "maximum_confidence_half_width": str(args.maximum_confidence_half_width),
        "maximum_calibration_error": str(args.maximum_calibration_error),
        "minimum_expected_net_r": str(args.minimum_expected_net_r),
        "minimum_conservative_net_r": str(args.minimum_conservative_net_r),
        "adverse_selection_r": str(args.adverse_selection_r),
        "operational_uncertainty_r": str(args.operational_uncertainty_r),
    },
    "untouched_test": {
        "all": {
            "trades": all_test.trades,
            "win_rate": str(all_test.win_rate),
            "expectancy_r": str(all_test.expectancy_r),
            "max_drawdown_r": str(all_test.max_drawdown_r),
            "total_r": str(all_test.total_r),
        },
        "ev_eligible": (
            {
                "trades": eligible_test.trades,
                "win_rate": str(eligible_test.win_rate),
                "expectancy_r": str(eligible_test.expectancy_r),
                "max_drawdown_r": str(eligible_test.max_drawdown_r),
                "total_r": str(eligible_test.total_r),
            }
            if eligible_test is not None
            else None
        ),
        "eligible_count": len(eligible_outcomes),
        "rejected_count": len(split.test) - len(eligible_outcomes),
    },
    "test_decisions": test_decisions,
    "interpretation": (
        "This report is an untouched-fold research result. Positive test expectancy is necessary but not sufficient for Practice promotion; "
        "ablation, drawdown, replay reproducibility, data-quality, execution and independent evidence requirements remain separate gates."
    ),
}
text = json.dumps(report, indent=2, sort_keys=True)
if args.output is not None:
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(text + "\n", encoding="utf-8")
print(text)
