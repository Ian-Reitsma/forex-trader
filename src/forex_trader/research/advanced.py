from __future__ import annotations

import hashlib
import json
import math
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Callable, Iterable, Mapping

from forex_trader.research.backtest import BacktestReport, BacktestTrade, OutcomeStatus, summarize_trades


@dataclass(frozen=True, slots=True)
class ReplayEvent:
    event_id: str
    event_type: str
    available_at: datetime
    provider_sequence: int
    payload: Mapping[str, object]

    def __post_init__(self) -> None:
        if self.available_at.tzinfo is None:
            raise ValueError("event available_at must be timezone-aware")
        if self.provider_sequence < 0:
            raise ValueError("provider_sequence cannot be negative")


class EventReplayScheduler:
    def __init__(self, events: Iterable[ReplayEvent]) -> None:
        self._events = tuple(sorted(events, key=lambda item: (item.available_at, item.provider_sequence, item.event_id)))

    def events(self) -> tuple[ReplayEvent, ...]:
        return self._events

    def run(self, consumer: Callable[[ReplayEvent], None]) -> int:
        for event in self._events:
            consumer(event)
        return len(self._events)


@dataclass(frozen=True, slots=True)
class ExperimentManifest:
    git_commit: str
    policy_fingerprint: str
    dataset_checksums: Mapping[str, str]
    provider_dataset_versions: Mapping[str, str]
    feature_versions: Mapping[str, str]
    model_versions: Mapping[str, str]
    calibration_version: str
    cost_model_version: str
    random_seed: int
    period_start: datetime
    period_end: datetime
    folds: tuple[str, ...]
    parameters: Mapping[str, str]

    def __post_init__(self) -> None:
        if self.period_start.tzinfo is None or self.period_end.tzinfo is None:
            raise ValueError("manifest period must be timezone-aware")
        if self.period_end <= self.period_start:
            raise ValueError("manifest period_end must be after period_start")

    @property
    def manifest_hash(self) -> str:
        payload = {
            "git_commit": self.git_commit,
            "policy_fingerprint": self.policy_fingerprint,
            "dataset_checksums": dict(sorted(self.dataset_checksums.items())),
            "provider_dataset_versions": dict(sorted(self.provider_dataset_versions.items())),
            "feature_versions": dict(sorted(self.feature_versions.items())),
            "model_versions": dict(sorted(self.model_versions.items())),
            "calibration_version": self.calibration_version,
            "cost_model_version": self.cost_model_version,
            "random_seed": self.random_seed,
            "period_start": self.period_start.isoformat(),
            "period_end": self.period_end.isoformat(),
            "folds": self.folds,
            "parameters": dict(sorted(self.parameters.items())),
        }
        return hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


@dataclass(frozen=True, slots=True)
class PredictionObservation:
    probability: Decimal
    outcome: bool
    cohort: str = "all"

    def __post_init__(self) -> None:
        if not Decimal("0") <= self.probability <= Decimal("1"):
            raise ValueError("probability must be in [0,1]")


@dataclass(frozen=True, slots=True)
class ReliabilityBin:
    lower: Decimal
    upper: Decimal
    count: int
    mean_probability: Decimal
    observed_rate: Decimal


@dataclass(frozen=True, slots=True)
class CalibrationReport:
    count: int
    brier_score: Decimal
    expected_calibration_error: Decimal
    bins: tuple[ReliabilityBin, ...]


def calibration_report(observations: Iterable[PredictionObservation], *, bin_count: int = 10) -> CalibrationReport:
    values = tuple(observations)
    if not values:
        raise ValueError("calibration requires observations")
    if bin_count < 2:
        raise ValueError("bin_count must be at least 2")
    brier = sum(((item.probability - Decimal(int(item.outcome))) ** 2 for item in values), Decimal("0")) / Decimal(len(values))
    bins: list[ReliabilityBin] = []
    ece = Decimal("0")
    width = Decimal("1") / Decimal(bin_count)
    for index in range(bin_count):
        lower = width * Decimal(index)
        upper = Decimal("1") if index == bin_count - 1 else width * Decimal(index + 1)
        if index == bin_count - 1:
            selected = [item for item in values if lower <= item.probability <= upper]
        else:
            selected = [item for item in values if lower <= item.probability < upper]
        if not selected:
            continue
        mean_probability = sum((item.probability for item in selected), Decimal("0")) / Decimal(len(selected))
        observed_rate = Decimal(sum(item.outcome for item in selected)) / Decimal(len(selected))
        ece += abs(mean_probability - observed_rate) * Decimal(len(selected)) / Decimal(len(values))
        bins.append(ReliabilityBin(lower, upper, len(selected), mean_probability, observed_rate))
    return CalibrationReport(len(values), brier, ece, tuple(bins))


@dataclass(frozen=True, slots=True)
class OutcomeEstimate:
    p_target_before_stop: Decimal
    p_stop_before_target: Decimal
    expected_mfe_r: Decimal
    expected_mae_r: Decimal
    expected_holding_bars: Decimal
    sample_size: int
    confidence_half_width: Decimal
    calibration_version: str
    p_timeout: Decimal = Decimal("0")
    expected_timeout_r: Decimal = Decimal("0")

    def __post_init__(self) -> None:
        probabilities = (self.p_target_before_stop, self.p_stop_before_target, self.p_timeout)
        if any(value < 0 or value > 1 for value in probabilities):
            raise ValueError("outcome probabilities must be in [0,1]")
        probability_sum = sum(probabilities, Decimal("0"))
        if abs(probability_sum - Decimal("1")) > Decimal("1e-24"):
            raise ValueError("target, stop and timeout probabilities must sum to 1")
        if self.sample_size < 0:
            raise ValueError("sample_size cannot be negative")
        if not Decimal("0") <= self.confidence_half_width <= Decimal("1"):
            raise ValueError("confidence_half_width must be in [0,1]")


class EmpiricalOutcomeModel:
    """Regularized three-outcome empirical baseline for target, stop, and time-exit paths."""

    def __init__(
        self,
        *,
        prior_wins: Decimal = Decimal("2"),
        prior_losses: Decimal = Decimal("2"),
        prior_timeouts: Decimal = Decimal("1"),
        calibration_version: str = "empirical-v2-three-outcome",
    ) -> None:
        if prior_wins <= 0 or prior_losses <= 0 or prior_timeouts <= 0:
            raise ValueError("outcome priors must be positive")
        self.prior_wins = prior_wins
        self.prior_losses = prior_losses
        self.prior_timeouts = prior_timeouts
        self.calibration_version = calibration_version

    def estimate(self, trades: Iterable[BacktestTrade]) -> OutcomeEstimate:
        sample = tuple(trades)
        count = len(sample)
        wins = sum(trade.status is OutcomeStatus.WIN for trade in sample)
        losses = sum(trade.status is OutcomeStatus.LOSS for trade in sample)
        timeouts = sum(trade.status is OutcomeStatus.TIMEOUT for trade in sample)
        if count == 0:
            # Preserve the established uninformed prior: before any observations, the
            # model is neutral between target and stop and does not invent a timeout rate.
            p_target = Decimal("0.5")
            p_stop = Decimal("0.5")
            p_timeout = Decimal("0")
            total = self.prior_wins + self.prior_losses
        else:
            alpha = self.prior_wins + Decimal(wins)
            beta = self.prior_losses + Decimal(losses)
            gamma = self.prior_timeouts + Decimal(timeouts)
            total = alpha + beta + gamma
            p_target = alpha / total
            p_stop = beta / total
            p_timeout = gamma / total
        timeout_sample = [item.r_multiple for item in sample if item.status is OutcomeStatus.TIMEOUT]
        if count:
            expected_mfe = sum((item.maximum_favorable_r for item in sample), Decimal("0")) / Decimal(count)
            expected_mae = sum((item.maximum_adverse_r for item in sample), Decimal("0")) / Decimal(count)
            expected_hold = sum((Decimal(item.bars_held) for item in sample), Decimal("0")) / Decimal(count)
        else:
            expected_mfe = expected_mae = expected_hold = Decimal("0")
        expected_timeout = (
            sum(timeout_sample, Decimal("0")) / Decimal(len(timeout_sample))
            if timeout_sample
            else Decimal("0")
        )
        variance = float(p_target * (Decimal("1") - p_target) / (total + Decimal("1")))
        half_width = Decimal(str(1.96 * math.sqrt(max(0.0, variance))))
        return OutcomeEstimate(
            p_target_before_stop=p_target,
            p_stop_before_target=p_stop,
            p_timeout=p_timeout,
            expected_mfe_r=expected_mfe,
            expected_mae_r=expected_mae,
            expected_holding_bars=expected_hold,
            expected_timeout_r=expected_timeout,
            sample_size=count,
            confidence_half_width=min(Decimal("1"), half_width),
            calibration_version=self.calibration_version,
        )


def expected_net_r(
    estimate: OutcomeEstimate,
    *,
    expected_gain_r: Decimal,
    expected_loss_r: Decimal = Decimal("1"),
    spread_cost_r: Decimal = Decimal("0"),
    slippage_cost_r: Decimal = Decimal("0"),
    commission_cost_r: Decimal = Decimal("0"),
    financing_cost_r: Decimal = Decimal("0"),
    adverse_selection_r: Decimal = Decimal("0"),
    operational_uncertainty_r: Decimal = Decimal("0"),
) -> Decimal:
    values = (
        expected_gain_r,
        expected_loss_r,
        spread_cost_r,
        slippage_cost_r,
        commission_cost_r,
        financing_cost_r,
        adverse_selection_r,
        operational_uncertainty_r,
    )
    if any(value < 0 for value in values):
        raise ValueError("gain/loss magnitudes and costs cannot be negative")
    costs = sum(values[2:], Decimal("0"))
    return (
        estimate.p_target_before_stop * expected_gain_r
        - estimate.p_stop_before_target * expected_loss_r
        + estimate.p_timeout * estimate.expected_timeout_r
        - costs
    )


@dataclass(frozen=True, slots=True)
class AblationResult:
    name: str
    report: BacktestReport
    delta_expectancy_r: Decimal


def compare_ablations(full_trades: Iterable[BacktestTrade], variants: Mapping[str, Iterable[BacktestTrade]]) -> tuple[AblationResult, ...]:
    full = summarize_trades(list(full_trades))
    results: list[AblationResult] = []
    for name, trades in sorted(variants.items()):
        report = summarize_trades(list(trades))
        results.append(AblationResult(name, report, report.expectancy_r - full.expectancy_r))
    return tuple(results)


@dataclass(frozen=True, slots=True)
class AttributionRecord:
    setup_family: str
    regime: str
    session: str
    instrument: str
    fundamental_alignment: str
    event_type: str
    flow_confirmation: str
    entry_style: str
    spread_bucket: str
    risk_bucket: str
    exit_reason: str
    r_multiple: Decimal


def attribution_expectancy(records: Iterable[AttributionRecord], *, field: str) -> dict[str, Decimal]:
    allowed = set(AttributionRecord.__dataclass_fields__) - {"r_multiple"}
    if field not in allowed:
        raise ValueError(f"unsupported attribution field: {field}")
    buckets: dict[str, list[Decimal]] = {}
    for record in records:
        key = str(getattr(record, field))
        buckets.setdefault(key, []).append(record.r_multiple)
    return {
        key: sum(values, Decimal("0")) / Decimal(len(values))
        for key, values in sorted(buckets.items())
        if values
    }
