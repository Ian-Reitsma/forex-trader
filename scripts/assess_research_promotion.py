"""Assess whether one setup family has enough evidence for further shadow promotion study.

This command is research-only. It never edits the system authority manifest and cannot grant
Practice or live-money execution. Missing ablations/replay/Phase-D evidence produces an
explicit insufficient-evidence result instead of falling back to aggregate P/L.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from dataclasses import asdict
from decimal import Decimal
from enum import Enum
from pathlib import Path
from typing import Mapping

from forex_trader.research.evidence import load_decision_evidence
from forex_trader.research.promotion_evidence import (
    AblationEvidence,
    PhaseDHoldoutEvidence,
    ReplayReproducibilityEvidence,
    assess_research_promotion,
    evidence_from_research_report,
)


def _load_json_object(path: Path) -> dict[str, object]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise SystemExit(f"{path} must contain one JSON object")
    return {str(key): value for key, value in payload.items()}


def _required_mapping(value: object, name: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise SystemExit(f"{name} must be a JSON object")
    return {str(key): item for key, item in value.items()}


def _required_text(value: object, name: str) -> str:
    if value is None:
        raise SystemExit(f"{name} is required")
    text = str(value).strip()
    if not text:
        raise SystemExit(f"{name} is required")
    return text


def _required_int(value: object, name: str) -> int:
    if value is None or value == "":
        raise SystemExit(f"{name} is required")
    return int(str(value))


def _required_decimal(value: object, name: str) -> Decimal:
    if value is None or value == "":
        raise SystemExit(f"{name} is required")
    return Decimal(str(value))


def _canonical_json_hash(path: Path) -> str:
    payload = json.loads(path.read_text(encoding="utf-8"))
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(canonical).hexdigest()


def _load_ablations(path: Path | None, *, dataset_id: str) -> tuple[AblationEvidence, ...]:
    if path is None:
        return ()
    payload = _load_json_object(path)
    rows = payload.get("ablations")
    if not isinstance(rows, list):
        raise SystemExit("ablation evidence must contain an 'ablations' array")
    results: list[AblationEvidence] = []
    for index, row in enumerate(rows):
        item = _required_mapping(row, f"ablations[{index}]")
        results.append(
            AblationEvidence(
                name=_required_text(item.get("name"), f"ablations[{index}].name"),
                full_expectancy_r=_required_decimal(
                    item.get("full_expectancy_r"),
                    f"ablations[{index}].full_expectancy_r",
                ),
                ablated_expectancy_r=_required_decimal(
                    item.get("ablated_expectancy_r"),
                    f"ablations[{index}].ablated_expectancy_r",
                ),
                sample_size=_required_int(item.get("sample_size"), f"ablations[{index}].sample_size"),
                dataset_id=_required_text(item.get("dataset_id"), f"ablations[{index}].dataset_id"),
            )
        )
    if any(item.dataset_id != dataset_id for item in results):
        # Keep the mismatch visible to the library assessment as a hard failure; this
        # early message only makes accidental file mixups easier to diagnose.
        print("warning: one or more ablations reference a different immutable dataset_id")
    return tuple(results)


def _load_replay(manifest: Path | None, result_paths: list[Path]) -> ReplayReproducibilityEvidence | None:
    if manifest is None and not result_paths:
        return None
    if manifest is None or not result_paths:
        raise SystemExit("replay evidence requires --replay-manifest and at least one --replay-result")
    manifest_hash = _canonical_json_hash(manifest)
    return ReplayReproducibilityEvidence(
        manifest_hash=manifest_hash,
        result_hashes=tuple(_canonical_json_hash(path) for path in result_paths),
    )


def _load_phase_d(path: Path | None) -> PhaseDHoldoutEvidence | None:
    if path is None:
        return None
    payload = _load_json_object(path)
    candidate = payload.get("confirmed_research_candidate")
    if candidate is None:
        return None
    policy_name = _required_text(candidate, "confirmed_research_candidate")
    holdout_scenarios = _required_int(payload.get("untouched_holdout_scenarios"), "untouched_holdout_scenarios")
    holdout = _required_mapping(payload.get("holdout"), "holdout")
    variants = holdout.get("variants")
    if not isinstance(variants, list) or len(variants) != 1:
        raise SystemExit("confirmed Phase-D report must contain exactly one untouched-holdout variant")
    variant = _required_mapping(variants[0], "holdout.variants[0]")
    policy = _required_mapping(variant.get("policy"), "holdout.variants[0].policy")
    reported_name = _required_text(policy.get("policy_name"), "holdout.variants[0].policy.policy_name")
    if reported_name != policy_name:
        raise SystemExit(f"Phase-D holdout policy mismatch: {reported_name} != {policy_name}")
    lower = _required_decimal(
        variant.get("lower_confidence_delta_r"),
        "holdout.variants[0].lower_confidence_delta_r",
    )
    recommendation = payload.get("holdout_recommendation")
    recommendation_mapping = _required_mapping(recommendation, "holdout_recommendation")
    confirmed = bool(recommendation_mapping.get("eligible"))
    return PhaseDHoldoutEvidence(
        policy_name=policy_name,
        confirmed=confirmed,
        holdout_scenarios=holdout_scenarios,
        lower_confidence_delta_r=lower,
    )


def _json_safe(value: object) -> object:
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, Enum):
        return value.value
    if hasattr(value, "__dataclass_fields__"):
        return _json_safe(asdict(value))
    if isinstance(value, dict):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        return [_json_safe(item) for item in value]
    return value


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("research_report", type=Path)
    parser.add_argument("decision_evidence", type=Path)
    parser.add_argument("--setup-family", required=True)
    parser.add_argument("--ablation-evidence", type=Path, default=None)
    parser.add_argument("--replay-manifest", type=Path, default=None)
    parser.add_argument("--replay-result", action="append", type=Path, default=[])
    parser.add_argument("--phase-d-report", type=Path, default=None)
    parser.add_argument("--proposed-phase-d-policy", default=None)
    parser.add_argument("--output", type=Path, default=None)
    args = parser.parse_args()

    report = _load_json_object(args.research_report)
    dataset = _required_mapping(report.get("dataset"), "dataset")
    dataset_id = _required_text(dataset.get("dataset_id"), "dataset.dataset_id")
    decisions = load_decision_evidence(args.decision_evidence)
    ablations = _load_ablations(args.ablation_evidence, dataset_id=dataset_id)
    replay = _load_replay(args.replay_manifest, list(args.replay_result))
    phase_d = _load_phase_d(args.phase_d_report)
    evidence = evidence_from_research_report(
        report,
        decisions,
        setup_family=args.setup_family,
        dataset_id=dataset_id,
        ablations=ablations,
        replay=replay,
        phase_d=phase_d,
    )
    assessment = assess_research_promotion(
        evidence,
        proposed_phase_d_policy=args.proposed_phase_d_policy,
    )
    payload = {
        "research_only": True,
        "execution_authority": False,
        "practice_authority_changed": False,
        "setup_family": evidence.setup_family,
        "policy_fingerprint": evidence.policy_fingerprint,
        "dataset_id": evidence.dataset_id,
        "evidence_digest": evidence.bundle_digest,
        "assessment": _json_safe(assessment),
        "metrics": {
            "labeled_trades": evidence.labeled_trades,
            "validation_predictions": evidence.validation_predictions,
            "validation_brier_score": str(evidence.validation_brier_score),
            "validation_ece": str(evidence.validation_ece),
            "untouched_test_trades": evidence.untouched_test_trades,
            "untouched_test_expectancy_r": str(evidence.untouched_test_expectancy_r),
            "untouched_test_total_r": str(evidence.untouched_test_total_r),
            "untouched_test_max_drawdown_r": str(evidence.untouched_test_max_drawdown_r),
            "ev_eligible_trades": evidence.ev_eligible_trades,
            "ev_eligible_expectancy_r": (
                str(evidence.ev_eligible_expectancy_r) if evidence.ev_eligible_expectancy_r is not None else None
            ),
            "decision_attempts": evidence.decision_attempts,
            "decision_errors": evidence.decision_errors,
            "decision_error_rate": str(evidence.decision_error_rate),
        },
        "interpretation": (
            "shadow_candidate is only a research nomination for further shadow comparison. "
            "This command never changes the machine-readable Practice authority manifest."
        ),
    }
    text = json.dumps(payload, indent=2, sort_keys=True)
    if args.output is not None:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(text + "\n", encoding="utf-8")
    print(text)


if __name__ == "__main__":
    main()
