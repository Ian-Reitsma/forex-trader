from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from decimal import Decimal
from enum import StrEnum
from typing import Iterable, Mapping

from forex_trader.research.evidence import DecisionEvidence


class ResearchPromotionDisposition(StrEnum):
    INSUFFICIENT_EVIDENCE = "insufficient_evidence"
    REJECTED = "rejected"
    SHADOW_CANDIDATE = "shadow_candidate"


@dataclass(frozen=True, slots=True)
class AblationEvidence:
    name: str
    full_expectancy_r: Decimal
    ablated_expectancy_r: Decimal
    sample_size: int
    dataset_id: str

    def __post_init__(self) -> None:
        if not self.name.strip() or not self.dataset_id.strip():
            raise ValueError("ablation name and dataset_id are required")
        if self.sample_size < 1:
            raise ValueError("ablation sample_size must be positive")

    @property
    def component_increment_r(self) -> Decimal:
        return self.full_expectancy_r - self.ablated_expectancy_r


@dataclass(frozen=True, slots=True)
class ReplayReproducibilityEvidence:
    manifest_hash: str
    result_hashes: tuple[str, ...]

    def __post_init__(self) -> None:
        if not self.manifest_hash.strip():
            raise ValueError("manifest_hash is required")
        if any(not item.strip() for item in self.result_hashes):
            raise ValueError("replay result hashes cannot be empty")

    @property
    def repetitions(self) -> int:
        return len(self.result_hashes)

    @property
    def reproducible(self) -> bool:
        return self.repetitions >= 2 and len(set(self.result_hashes)) == 1


@dataclass(frozen=True, slots=True)
class PhaseDHoldoutEvidence:
    policy_name: str
    confirmed: bool
    holdout_scenarios: int
    lower_confidence_delta_r: Decimal

    def __post_init__(self) -> None:
        if not self.policy_name.strip():
            raise ValueError("Phase D policy_name is required")
        if self.holdout_scenarios < 0:
            raise ValueError("Phase D holdout_scenarios cannot be negative")


@dataclass(frozen=True, slots=True)
class ResearchPromotionEvidence:
    setup_family: str
    policy_fingerprint: str
    dataset_id: str
    labeled_trades: int
    validation_predictions: int
    validation_brier_score: Decimal
    validation_ece: Decimal
    untouched_test_trades: int
    untouched_test_expectancy_r: Decimal
    untouched_test_total_r: Decimal
    untouched_test_max_drawdown_r: Decimal
    ev_eligible_trades: int
    ev_eligible_expectancy_r: Decimal | None
    ev_eligible_total_r: Decimal | None
    ev_eligible_max_drawdown_r: Decimal | None
    decision_attempts: int
    decision_errors: int
    ablations: tuple[AblationEvidence, ...]
    replay: ReplayReproducibilityEvidence | None
    phase_d: PhaseDHoldoutEvidence | None = None

    def __post_init__(self) -> None:
        if not self.setup_family.strip() or not self.policy_fingerprint.strip() or not self.dataset_id.strip():
            raise ValueError("setup_family, policy_fingerprint and dataset_id are required")
        counts = (
            self.labeled_trades,
            self.validation_predictions,
            self.untouched_test_trades,
            self.ev_eligible_trades,
            self.decision_attempts,
            self.decision_errors,
        )
        if any(value < 0 for value in counts):
            raise ValueError("research evidence counts cannot be negative")
        if self.decision_errors > self.decision_attempts:
            raise ValueError("decision_errors cannot exceed decision_attempts")
        if not Decimal("0") <= self.validation_ece <= Decimal("1"):
            raise ValueError("validation_ece must be in [0,1]")
        if not Decimal("0") <= self.validation_brier_score <= Decimal("1"):
            raise ValueError("validation_brier_score must be in [0,1]")

    @property
    def decision_error_rate(self) -> Decimal:
        if self.decision_attempts == 0:
            return Decimal("1")
        return Decimal(self.decision_errors) / Decimal(self.decision_attempts)

    @property
    def bundle_digest(self) -> str:
        payload = {
            "setup_family": self.setup_family,
            "policy_fingerprint": self.policy_fingerprint,
            "dataset_id": self.dataset_id,
            "labeled_trades": self.labeled_trades,
            "validation_predictions": self.validation_predictions,
            "validation_brier_score": str(self.validation_brier_score),
            "validation_ece": str(self.validation_ece),
            "untouched_test_trades": self.untouched_test_trades,
            "untouched_test_expectancy_r": str(self.untouched_test_expectancy_r),
            "untouched_test_total_r": str(self.untouched_test_total_r),
            "untouched_test_max_drawdown_r": str(self.untouched_test_max_drawdown_r),
            "ev_eligible_trades": self.ev_eligible_trades,
            "ev_eligible_expectancy_r": str(self.ev_eligible_expectancy_r) if self.ev_eligible_expectancy_r is not None else None,
            "ev_eligible_total_r": str(self.ev_eligible_total_r) if self.ev_eligible_total_r is not None else None,
            "ev_eligible_max_drawdown_r": str(self.ev_eligible_max_drawdown_r) if self.ev_eligible_max_drawdown_r is not None else None,
            "decision_attempts": self.decision_attempts,
            "decision_errors": self.decision_errors,
            "ablations": [
                {
                    "name": item.name,
                    "full_expectancy_r": str(item.full_expectancy_r),
                    "ablated_expectancy_r": str(item.ablated_expectancy_r),
                    "sample_size": item.sample_size,
                    "dataset_id": item.dataset_id,
                }
                for item in sorted(self.ablations, key=lambda item: item.name)
            ],
            "replay": (
                {
                    "manifest_hash": self.replay.manifest_hash,
                    "result_hashes": self.replay.result_hashes,
                }
                if self.replay is not None else None
            ),
            "phase_d": (
                {
                    "policy_name": self.phase_d.policy_name,
                    "confirmed": self.phase_d.confirmed,
                    "holdout_scenarios": self.phase_d.holdout_scenarios,
                    "lower_confidence_delta_r": str(self.phase_d.lower_confidence_delta_r),
                }
                if self.phase_d is not None else None
            ),
        }
        encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
        return hashlib.sha256(encoded).hexdigest()


@dataclass(frozen=True, slots=True)
class ResearchPromotionPolicy:
    minimum_labeled_trades: int = 200
    minimum_validation_predictions: int = 40
    maximum_validation_ece: Decimal = Decimal("0.08")
    maximum_validation_brier: Decimal = Decimal("0.30")
    minimum_untouched_test_trades: int = 40
    minimum_untouched_expectancy_r: Decimal = Decimal("0")
    maximum_untouched_drawdown_r: Decimal = Decimal("8")
    minimum_ev_eligible_trades: int = 20
    minimum_ev_eligible_expectancy_r: Decimal = Decimal("0")
    maximum_decision_error_rate: Decimal = Decimal("0.01")
    required_ablations: tuple[str, ...] = (
        "no_fundamentals",
        "no_flow",
        "no_session",
        "no_zone_quality",
        "no_retest",
    )
    maximum_ablation_outperformance_r: Decimal = Decimal("0.05")
    minimum_replay_repetitions: int = 2
    minimum_phase_d_holdout_scenarios: int = 30

    def __post_init__(self) -> None:
        counts = (
            self.minimum_labeled_trades,
            self.minimum_validation_predictions,
            self.minimum_untouched_test_trades,
            self.minimum_ev_eligible_trades,
            self.minimum_replay_repetitions,
            self.minimum_phase_d_holdout_scenarios,
        )
        if any(value < 1 for value in counts):
            raise ValueError("research promotion sample requirements must be positive")
        for value, name in (
            (self.maximum_validation_ece, "maximum_validation_ece"),
            (self.maximum_validation_brier, "maximum_validation_brier"),
            (self.maximum_decision_error_rate, "maximum_decision_error_rate"),
        ):
            if not Decimal("0") <= value <= Decimal("1"):
                raise ValueError(f"{name} must be in [0,1]")
        if self.maximum_untouched_drawdown_r < 0 or self.maximum_ablation_outperformance_r < 0:
            raise ValueError("drawdown and ablation tolerances cannot be negative")
        if len(set(self.required_ablations)) != len(self.required_ablations):
            raise ValueError("required_ablations must be unique")


@dataclass(frozen=True, slots=True)
class ResearchPromotionAssessment:
    disposition: ResearchPromotionDisposition
    setup_family: str
    policy_fingerprint: str
    evidence_digest: str
    hard_failures: tuple[str, ...]
    missing_evidence: tuple[str, ...]
    passed_checks: tuple[str, ...]
    practice_authority_changed: bool = False

    @property
    def shadow_candidate(self) -> bool:
        return self.disposition is ResearchPromotionDisposition.SHADOW_CANDIDATE


def assess_research_promotion(
    evidence: ResearchPromotionEvidence,
    *,
    policy: ResearchPromotionPolicy | None = None,
    proposed_phase_d_policy: str | None = None,
) -> ResearchPromotionAssessment:
    rules = policy or ResearchPromotionPolicy()
    hard: list[str] = []
    missing: list[str] = []
    passed: list[str] = []

    _minimum_check(evidence.labeled_trades, rules.minimum_labeled_trades, "labeled_trades", hard, passed)
    _minimum_check(
        evidence.validation_predictions,
        rules.minimum_validation_predictions,
        "validation_predictions",
        hard,
        passed,
    )
    _maximum_decimal_check(evidence.validation_ece, rules.maximum_validation_ece, "validation_ece", hard, passed)
    _maximum_decimal_check(
        evidence.validation_brier_score,
        rules.maximum_validation_brier,
        "validation_brier_score",
        hard,
        passed,
    )
    _minimum_check(
        evidence.untouched_test_trades,
        rules.minimum_untouched_test_trades,
        "untouched_test_trades",
        hard,
        passed,
    )
    if evidence.untouched_test_expectancy_r <= rules.minimum_untouched_expectancy_r:
        hard.append(
            f"untouched_test_expectancy_r {evidence.untouched_test_expectancy_r} <= {rules.minimum_untouched_expectancy_r}"
        )
    else:
        passed.append("untouched_test_expectancy_r")
    if evidence.untouched_test_total_r <= 0:
        hard.append(f"untouched_test_total_r {evidence.untouched_test_total_r} <= 0")
    else:
        passed.append("untouched_test_total_r")
    _maximum_decimal_check(
        evidence.untouched_test_max_drawdown_r,
        rules.maximum_untouched_drawdown_r,
        "untouched_test_max_drawdown_r",
        hard,
        passed,
    )
    _minimum_check(
        evidence.ev_eligible_trades,
        rules.minimum_ev_eligible_trades,
        "ev_eligible_trades",
        hard,
        passed,
    )
    if evidence.ev_eligible_expectancy_r is None or evidence.ev_eligible_total_r is None:
        missing.append("ev_eligible_untouched_test_metrics")
    else:
        if evidence.ev_eligible_expectancy_r <= rules.minimum_ev_eligible_expectancy_r:
            hard.append(
                f"ev_eligible_expectancy_r {evidence.ev_eligible_expectancy_r} <= {rules.minimum_ev_eligible_expectancy_r}"
            )
        else:
            passed.append("ev_eligible_expectancy_r")
        if evidence.ev_eligible_total_r <= 0:
            hard.append(f"ev_eligible_total_r {evidence.ev_eligible_total_r} <= 0")
        else:
            passed.append("ev_eligible_total_r")
    if evidence.decision_error_rate > rules.maximum_decision_error_rate:
        hard.append(f"decision_error_rate {evidence.decision_error_rate} > {rules.maximum_decision_error_rate}")
    else:
        passed.append("decision_error_rate")

    ablation_by_name = {item.name: item for item in evidence.ablations}
    for name in rules.required_ablations:
        item = ablation_by_name.get(name)
        if item is None:
            missing.append(f"ablation:{name}")
            continue
        if item.dataset_id != evidence.dataset_id:
            hard.append(f"ablation:{name} dataset_id mismatch")
            continue
        if item.ablated_expectancy_r - item.full_expectancy_r > rules.maximum_ablation_outperformance_r:
            hard.append(
                f"ablation:{name} outperforms full policy by "
                f"{item.ablated_expectancy_r - item.full_expectancy_r}R > {rules.maximum_ablation_outperformance_r}R"
            )
        else:
            passed.append(f"ablation:{name}")

    if evidence.replay is None:
        missing.append("replay_reproducibility")
    elif evidence.replay.repetitions < rules.minimum_replay_repetitions:
        missing.append(
            f"replay_reproducibility:{evidence.replay.repetitions}/{rules.minimum_replay_repetitions}_repetitions"
        )
    elif not evidence.replay.reproducible:
        hard.append("replay result hashes differ under the same manifest")
    else:
        passed.append("replay_reproducibility")

    if proposed_phase_d_policy is not None:
        requested = proposed_phase_d_policy.strip()
        if not requested:
            raise ValueError("proposed_phase_d_policy cannot be empty")
        if evidence.phase_d is None:
            missing.append(f"phase_d_holdout:{requested}")
        elif evidence.phase_d.policy_name != requested:
            hard.append(
                f"phase_d policy mismatch: evidence={evidence.phase_d.policy_name} proposed={requested}"
            )
        elif not evidence.phase_d.confirmed:
            hard.append(f"phase_d policy {requested} was not confirmed on untouched holdout")
        elif evidence.phase_d.holdout_scenarios < rules.minimum_phase_d_holdout_scenarios:
            hard.append(
                f"phase_d holdout_scenarios {evidence.phase_d.holdout_scenarios} < "
                f"{rules.minimum_phase_d_holdout_scenarios}"
            )
        elif evidence.phase_d.lower_confidence_delta_r <= 0:
            hard.append(
                f"phase_d lower_confidence_delta_r {evidence.phase_d.lower_confidence_delta_r} <= 0"
            )
        else:
            passed.append(f"phase_d_holdout:{requested}")

    if hard:
        disposition = ResearchPromotionDisposition.REJECTED
    elif missing:
        disposition = ResearchPromotionDisposition.INSUFFICIENT_EVIDENCE
    else:
        disposition = ResearchPromotionDisposition.SHADOW_CANDIDATE
    return ResearchPromotionAssessment(
        disposition=disposition,
        setup_family=evidence.setup_family,
        policy_fingerprint=evidence.policy_fingerprint,
        evidence_digest=evidence.bundle_digest,
        hard_failures=tuple(hard),
        missing_evidence=tuple(missing),
        passed_checks=tuple(passed),
        practice_authority_changed=False,
    )


def evidence_from_research_report(
    report: Mapping[str, object],
    decisions: Iterable[DecisionEvidence],
    *,
    setup_family: str,
    dataset_id: str,
    ablations: Iterable[AblationEvidence] = (),
    replay: ReplayReproducibilityEvidence | None = None,
    phase_d: PhaseDHoldoutEvidence | None = None,
) -> ResearchPromotionEvidence:
    if report.get("research_only") is not True or report.get("execution_authority") is not False:
        raise ValueError("research report must be explicitly research-only with no execution authority")
    requested_setup = setup_family.strip()
    if not requested_setup:
        raise ValueError("setup_family is required")
    report_setup = _optional_text(report.get("setup_family_filter"))
    if report_setup != requested_setup:
        raise ValueError(
            f"research report is not isolated to setup_family={requested_setup}; report filter={report_setup!r}"
        )
    observed = _string_tuple(report.get("setup_families_observed"))
    if observed != (requested_setup,):
        raise ValueError(f"research report observed setup families {observed}; expected only {requested_setup}")
    policy_fingerprint = _required_text(report.get("policy_fingerprint"), "policy_fingerprint")
    decision_rows = tuple(item for item in decisions if item.policy_fingerprint == policy_fingerprint)
    if not decision_rows:
        raise ValueError("no decision evidence matches the research report policy fingerprint")
    decision_fingerprints = {item.policy_fingerprint for item in decision_rows}
    if decision_fingerprints != {policy_fingerprint}:
        raise ValueError("decision evidence contains inconsistent policy fingerprints")

    dataset = _required_mapping(report.get("dataset"), "dataset")
    calibration = _required_mapping(report.get("validation_calibration"), "validation_calibration")
    untouched = _required_mapping(report.get("untouched_test"), "untouched_test")
    untouched_all = _required_mapping(untouched.get("all"), "untouched_test.all")
    ev_eligible_raw = untouched.get("ev_eligible")
    ev_eligible = _required_mapping(ev_eligible_raw, "untouched_test.ev_eligible") if ev_eligible_raw is not None else None

    return ResearchPromotionEvidence(
        setup_family=requested_setup,
        policy_fingerprint=policy_fingerprint,
        dataset_id=dataset_id,
        labeled_trades=_required_int(dataset.get("labeled_trades"), "dataset.labeled_trades"),
        validation_predictions=_required_int(calibration.get("count"), "validation_calibration.count"),
        validation_brier_score=_required_decimal(calibration.get("brier_score"), "validation_calibration.brier_score"),
        validation_ece=_required_decimal(
            calibration.get("expected_calibration_error"),
            "validation_calibration.expected_calibration_error",
        ),
        untouched_test_trades=_required_int(untouched_all.get("trades"), "untouched_test.all.trades"),
        untouched_test_expectancy_r=_required_decimal(
            untouched_all.get("expectancy_r"),
            "untouched_test.all.expectancy_r",
        ),
        untouched_test_total_r=_required_decimal(untouched_all.get("total_r"), "untouched_test.all.total_r"),
        untouched_test_max_drawdown_r=_required_decimal(
            untouched_all.get("max_drawdown_r"),
            "untouched_test.all.max_drawdown_r",
        ),
        ev_eligible_trades=_required_int(untouched.get("eligible_count"), "untouched_test.eligible_count"),
        ev_eligible_expectancy_r=(
            _required_decimal(ev_eligible.get("expectancy_r"), "untouched_test.ev_eligible.expectancy_r")
            if ev_eligible is not None else None
        ),
        ev_eligible_total_r=(
            _required_decimal(ev_eligible.get("total_r"), "untouched_test.ev_eligible.total_r")
            if ev_eligible is not None else None
        ),
        ev_eligible_max_drawdown_r=(
            _required_decimal(ev_eligible.get("max_drawdown_r"), "untouched_test.ev_eligible.max_drawdown_r")
            if ev_eligible is not None else None
        ),
        decision_attempts=len(decision_rows),
        decision_errors=sum(item.error_type is not None for item in decision_rows),
        ablations=tuple(ablations),
        replay=replay,
        phase_d=phase_d,
    )


def _minimum_check(value: int, minimum: int, name: str, hard: list[str], passed: list[str]) -> None:
    if value < minimum:
        hard.append(f"{name} {value} < {minimum}")
    else:
        passed.append(name)


def _maximum_decimal_check(
    value: Decimal,
    maximum: Decimal,
    name: str,
    hard: list[str],
    passed: list[str],
) -> None:
    if value > maximum:
        hard.append(f"{name} {value} > {maximum}")
    else:
        passed.append(name)


def _required_mapping(value: object, name: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise ValueError(f"{name} must be an object")
    return {str(key): item for key, item in value.items()}


def _optional_text(value: object) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _required_text(value: object, name: str) -> str:
    text = _optional_text(value)
    if text is None:
        raise ValueError(f"{name} is required")
    return text


def _required_decimal(value: object, name: str) -> Decimal:
    if value is None or value == "":
        raise ValueError(f"{name} is required")
    return Decimal(str(value))


def _required_int(value: object, name: str) -> int:
    if value is None or value == "":
        raise ValueError(f"{name} is required")
    return int(str(value))


def _string_tuple(value: object) -> tuple[str, ...]:
    if not isinstance(value, (list, tuple)):
        return ()
    return tuple(str(item) for item in value)
