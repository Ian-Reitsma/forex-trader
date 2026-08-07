from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Iterable, Mapping

from forex_trader.research.advanced import (
    CalibrationReport,
    EmpiricalOutcomeModel,
    OutcomeEstimate,
    PredictionObservation,
    calibration_report,
)
from forex_trader.research.backtest import BacktestTrade
from forex_trader.research.evidence import DecisionEvidence


@dataclass(frozen=True, slots=True)
class LabeledDecision:
    decision: DecisionEvidence
    outcome: BacktestTrade

    def __post_init__(self) -> None:
        if self.decision.instrument != self.outcome.instrument:
            raise ValueError("decision and outcome instruments must match")
        if self.decision.signal_time is None:
            raise ValueError("labeled decision requires signal_time")


@dataclass(frozen=True, slots=True)
class ChronologicalSplit:
    train: tuple[LabeledDecision, ...]
    validation: tuple[LabeledDecision, ...]
    test: tuple[LabeledDecision, ...]


@dataclass(frozen=True, slots=True)
class CohortOutcomeEstimate:
    cohort: str
    estimate: OutcomeEstimate


@dataclass(frozen=True, slots=True)
class CohortPrediction:
    cohort: str
    probability: Decimal
    confidence_half_width: Decimal
    outcome: bool
    signal_time_iso: str
    instrument: str


@dataclass(frozen=True, slots=True)
class CohortCalibrationSummary:
    overall: CalibrationReport
    by_cohort: Mapping[str, CalibrationReport]
    predictions: tuple[CohortPrediction, ...]


@dataclass(frozen=True, slots=True)
class ExpectedValueDecision:
    eligible: bool
    cohort: str
    expected_net_r: Decimal
    conservative_net_r: Decimal
    probability_target: Decimal
    probability_target_lower: Decimal
    sample_size: int
    confidence_half_width: Decimal
    calibration_error: Decimal | None
    reasons: tuple[str, ...]


def chronological_split(
    records: Iterable[LabeledDecision],
    *,
    train_fraction: Decimal = Decimal("0.60"),
    validation_fraction: Decimal = Decimal("0.20"),
) -> ChronologicalSplit:
    values = tuple(sorted(records, key=lambda item: (item.decision.signal_time, item.decision.instrument, item.decision.trace_id or "")))
    if len(values) < 3:
        raise ValueError("chronological split requires at least three labeled decisions")
    if not Decimal("0") < train_fraction < Decimal("1"):
        raise ValueError("train_fraction must be in (0,1)")
    if not Decimal("0") < validation_fraction < Decimal("1"):
        raise ValueError("validation_fraction must be in (0,1)")
    if train_fraction + validation_fraction >= Decimal("1"):
        raise ValueError("train and validation fractions must leave a non-empty test fraction")

    train_end = max(1, int(Decimal(len(values)) * train_fraction))
    validation_end = max(train_end + 1, int(Decimal(len(values)) * (train_fraction + validation_fraction)))
    validation_end = min(validation_end, len(values) - 1)
    return ChronologicalSplit(
        train=values[:train_end],
        validation=values[train_end:validation_end],
        test=values[validation_end:],
    )


def cohort_hierarchy(decision: DecisionEvidence, *, include_instrument: bool = True) -> tuple[str, ...]:
    setup = decision.setup_family or "unknown_setup"
    regime = decision.regime or "unknown_regime"
    session = decision.session_phase or "unknown_session"
    keys: list[str] = []
    if include_instrument:
        keys.append(f"setup={setup}|regime={regime}|session={session}|instrument={decision.instrument}")
    keys.extend(
        [
            f"setup={setup}|regime={regime}|session={session}",
            f"setup={setup}|regime={regime}",
            f"setup={setup}",
            "all",
        ]
    )
    return tuple(keys)


class HierarchicalOutcomeModel:
    """Hierarchical empirical model with explicit fallback instead of sparse-cohort overfit."""

    def __init__(
        self,
        records: Iterable[LabeledDecision],
        *,
        minimum_cohort_trades: int = 30,
        include_instrument: bool = True,
        model: EmpiricalOutcomeModel | None = None,
    ) -> None:
        if minimum_cohort_trades < 2:
            raise ValueError("minimum_cohort_trades must be at least 2")
        self.minimum_cohort_trades = minimum_cohort_trades
        self.include_instrument = include_instrument
        self.model = model or EmpiricalOutcomeModel()
        buckets: dict[str, list[BacktestTrade]] = {}
        for record in records:
            for key in cohort_hierarchy(record.decision, include_instrument=include_instrument):
                buckets.setdefault(key, []).append(record.outcome)
        self._buckets = {key: tuple(value) for key, value in buckets.items()}

    def estimate(self, decision: DecisionEvidence) -> CohortOutcomeEstimate:
        hierarchy = cohort_hierarchy(decision, include_instrument=self.include_instrument)
        for key in hierarchy:
            trades = self._buckets.get(key, ())
            if len(trades) >= self.minimum_cohort_trades:
                return CohortOutcomeEstimate(key, self.model.estimate(trades))
        all_trades = self._buckets.get("all", ())
        if not all_trades:
            raise ValueError("outcome model has no labeled trades")
        return CohortOutcomeEstimate("all:insufficient_specific_history", self.model.estimate(all_trades))


class ResearchExpectedValueGate:
    """Research-only EV gate. It cannot authorize broker execution."""

    def __init__(
        self,
        *,
        minimum_sample_size: int = 50,
        maximum_confidence_half_width: Decimal = Decimal("0.20"),
        maximum_calibration_error: Decimal = Decimal("0.08"),
        minimum_expected_net_r: Decimal = Decimal("0"),
        minimum_conservative_net_r: Decimal = Decimal("0"),
        require_calibration: bool = True,
    ) -> None:
        if minimum_sample_size < 2:
            raise ValueError("minimum_sample_size must be at least 2")
        for value, name in (
            (maximum_confidence_half_width, "maximum_confidence_half_width"),
            (maximum_calibration_error, "maximum_calibration_error"),
        ):
            if not Decimal("0") <= value <= Decimal("1"):
                raise ValueError(f"{name} must be in [0,1]")
        self.minimum_sample_size = minimum_sample_size
        self.maximum_confidence_half_width = maximum_confidence_half_width
        self.maximum_calibration_error = maximum_calibration_error
        self.minimum_expected_net_r = minimum_expected_net_r
        self.minimum_conservative_net_r = minimum_conservative_net_r
        self.require_calibration = require_calibration

    def evaluate(
        self,
        cohort_estimate: CohortOutcomeEstimate,
        *,
        expected_gain_r: Decimal,
        expected_loss_r: Decimal = Decimal("1"),
        spread_cost_r: Decimal = Decimal("0"),
        slippage_cost_r: Decimal = Decimal("0"),
        commission_cost_r: Decimal = Decimal("0"),
        financing_cost_r: Decimal = Decimal("0"),
        adverse_selection_r: Decimal = Decimal("0"),
        operational_uncertainty_r: Decimal = Decimal("0"),
        calibration_error: Decimal | None = None,
    ) -> ExpectedValueDecision:
        magnitudes = (
            expected_gain_r,
            expected_loss_r,
            spread_cost_r,
            slippage_cost_r,
            commission_cost_r,
            financing_cost_r,
            adverse_selection_r,
            operational_uncertainty_r,
        )
        if any(value < 0 for value in magnitudes):
            raise ValueError("gain/loss magnitudes and costs cannot be negative")
        estimate = cohort_estimate.estimate
        costs = sum(magnitudes[2:], Decimal("0"))
        expected = (
            estimate.p_target_before_stop * expected_gain_r
            - estimate.p_stop_before_target * expected_loss_r
            - costs
        )
        lower_target = max(Decimal("0"), estimate.p_target_before_stop - estimate.confidence_half_width)
        upper_stop = min(Decimal("1"), estimate.p_stop_before_target + estimate.confidence_half_width)
        conservative = lower_target * expected_gain_r - upper_stop * expected_loss_r - costs

        reasons: list[str] = []
        if estimate.sample_size < self.minimum_sample_size:
            reasons.append(f"sample_size {estimate.sample_size} < {self.minimum_sample_size}")
        if estimate.confidence_half_width > self.maximum_confidence_half_width:
            reasons.append(
                f"confidence_half_width {estimate.confidence_half_width} > {self.maximum_confidence_half_width}"
            )
        if self.require_calibration and calibration_error is None:
            reasons.append("calibration_error is required")
        if calibration_error is not None and calibration_error > self.maximum_calibration_error:
            reasons.append(f"calibration_error {calibration_error} > {self.maximum_calibration_error}")
        if expected <= self.minimum_expected_net_r:
            reasons.append(f"expected_net_r {expected} <= {self.minimum_expected_net_r}")
        if conservative <= self.minimum_conservative_net_r:
            reasons.append(f"conservative_net_r {conservative} <= {self.minimum_conservative_net_r}")
        return ExpectedValueDecision(
            eligible=not reasons,
            cohort=cohort_estimate.cohort,
            expected_net_r=expected,
            conservative_net_r=conservative,
            probability_target=estimate.p_target_before_stop,
            probability_target_lower=lower_target,
            sample_size=estimate.sample_size,
            confidence_half_width=estimate.confidence_half_width,
            calibration_error=calibration_error,
            reasons=tuple(reasons),
        )


def walk_forward_cohort_calibration(
    records: Iterable[LabeledDecision],
    *,
    minimum_history: int = 30,
    minimum_cohort_trades: int = 20,
    include_instrument: bool = False,
    model: EmpiricalOutcomeModel | None = None,
) -> CohortCalibrationSummary:
    values = tuple(sorted(records, key=lambda item: (item.decision.signal_time, item.decision.instrument, item.decision.trace_id or "")))
    if minimum_history < 2 or minimum_cohort_trades < 2:
        raise ValueError("history thresholds must be at least 2")
    outcome_model = model or EmpiricalOutcomeModel()
    history: dict[str, list[BacktestTrade]] = {}
    predictions: list[CohortPrediction] = []

    for record in values:
        hierarchy = cohort_hierarchy(record.decision, include_instrument=include_instrument)
        selected_key: str | None = None
        selected_trades: list[BacktestTrade] | None = None
        for key in hierarchy:
            bucket = history.get(key, [])
            required = minimum_history if key == "all" else minimum_cohort_trades
            if len(bucket) >= required:
                selected_key = key
                selected_trades = bucket
                break
        if selected_key is not None and selected_trades is not None:
            estimate = outcome_model.estimate(selected_trades)
            signal_time = record.decision.signal_time
            assert signal_time is not None
            predictions.append(
                CohortPrediction(
                    cohort=selected_key,
                    probability=estimate.p_target_before_stop,
                    confidence_half_width=estimate.confidence_half_width,
                    outcome=record.outcome.r_multiple > 0,
                    signal_time_iso=signal_time.isoformat(),
                    instrument=record.decision.instrument,
                )
            )
        for key in hierarchy:
            history.setdefault(key, []).append(record.outcome)

    if not predictions:
        raise ValueError("insufficient chronological history to produce walk-forward predictions")
    overall = calibration_report(
        PredictionObservation(item.probability, item.outcome, cohort=item.cohort)
        for item in predictions
    )
    grouped: dict[str, list[PredictionObservation]] = {}
    for item in predictions:
        grouped.setdefault(item.cohort, []).append(
            PredictionObservation(item.probability, item.outcome, cohort=item.cohort)
        )
    by_cohort = {key: calibration_report(items) for key, items in sorted(grouped.items())}
    return CohortCalibrationSummary(overall=overall, by_cohort=by_cohort, predictions=tuple(predictions))
