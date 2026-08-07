from __future__ import annotations

import random
from dataclasses import dataclass, replace
from datetime import datetime
from decimal import Decimal
from typing import Iterable

from forex_trader.domain.models import Candle, TradeCandidate
from forex_trader.research.backtest import OutcomeStatus
from forex_trader.research.management import ManagementPolicy, STRUCTURAL_SINGLE_TARGET, evaluate_management_outcome
from forex_trader.research.order_types import EntryStyleOutcome, OrderStyle, evaluate_entry_style


@dataclass(frozen=True, slots=True)
class PhaseDPolicy:
    name: str
    order_style: OrderStyle = OrderStyle.MARKET
    offset_r: Decimal = Decimal("0.25")
    entry_slippage_pips: Decimal = Decimal("0.10")
    exit_slippage_pips: Decimal = Decimal("0.10")
    maximum_entry_bars: int = 6
    maximum_holding_bars: int = 24
    management: ManagementPolicy = STRUCTURAL_SINGLE_TARGET

    def __post_init__(self) -> None:
        if not self.name.strip():
            raise ValueError("Phase D policy name is required")
        if self.offset_r < 0:
            raise ValueError("offset_r cannot be negative")
        if self.entry_slippage_pips < 0 or self.exit_slippage_pips < 0:
            raise ValueError("slippage assumptions cannot be negative")
        if self.maximum_entry_bars < 1 or self.maximum_holding_bars < 1:
            raise ValueError("Phase D bar horizons must be positive")


@dataclass(frozen=True, slots=True)
class PhaseDScenario:
    signal_key: str
    candidate: TradeCandidate
    future_candles: tuple[Candle, ...]
    spread_pips: Decimal = Decimal("0")

    def __post_init__(self) -> None:
        if not self.signal_key.strip():
            raise ValueError("signal_key is required")
        if not self.future_candles:
            raise ValueError("Phase D scenario requires future candles")
        if self.spread_pips < 0:
            raise ValueError("scenario spread cannot be negative")


@dataclass(frozen=True, slots=True)
class PhaseDSignalOutcome:
    signal_key: str
    policy_name: str
    signal_time: datetime | None
    filled: bool
    fill_price: Decimal | None
    bars_to_fill: int | None
    realized_status: OutcomeStatus | None
    r_multiple: Decimal
    bars_held_after_fill: int
    opportunity_cost_r: Decimal
    entry_adverse_selection_r: Decimal
    entry_termination_reason: str
    management_exit_reason: str
    management_valid: bool
    ambiguous: bool


@dataclass(frozen=True, slots=True)
class PhaseDPolicyReport:
    policy_name: str
    scenarios: int
    fills: int
    fill_rate: Decimal
    management_valid: int
    positive_signals: int
    total_r: Decimal
    average_r_per_signal: Decimal
    average_r_per_fill: Decimal
    max_drawdown_r: Decimal
    average_opportunity_cost_r: Decimal
    average_entry_adverse_selection_r: Decimal
    invalidated_before_fill: int
    target_missed_before_fill: int
    ambiguous_pre_fill: int
    expired_unfilled: int
    invalid_management_geometry: int
    ambiguous_fraction: Decimal


@dataclass(frozen=True, slots=True)
class PairedVariantComparison:
    policy: PhaseDPolicyReport
    mean_delta_r_per_signal: Decimal
    lower_confidence_delta_r: Decimal
    upper_confidence_delta_r: Decimal
    paired_wins: int
    paired_losses: int
    paired_ties: int


@dataclass(frozen=True, slots=True)
class PhaseDComparisonReport:
    baseline: PhaseDPolicyReport
    variants: tuple[PairedVariantComparison, ...]
    scenario_count: int
    confidence: Decimal
    bootstrap_iterations: int
    bootstrap_seed: int


@dataclass(frozen=True, slots=True)
class PhaseDResearchRecommendation:
    eligible: bool
    policy_name: str | None
    lower_confidence_delta_r: Decimal
    reasons: tuple[str, ...]


def evaluate_phase_d_policy(scenario: PhaseDScenario, policy: PhaseDPolicy) -> PhaseDSignalOutcome:
    entry = evaluate_entry_style(
        scenario.candidate,
        scenario.future_candles,
        policy.order_style,
        offset_r=policy.offset_r,
        slippage_pips=policy.entry_slippage_pips,
        spread_pips=scenario.spread_pips,
        maximum_bars=policy.maximum_entry_bars,
    )
    signal_time = scenario.candidate.signal_time if isinstance(scenario.candidate.signal_time, datetime) else None
    if not entry.filled or entry.fill_price is None:
        return PhaseDSignalOutcome(
            signal_key=scenario.signal_key,
            policy_name=policy.name,
            signal_time=signal_time,
            filled=False,
            fill_price=None,
            bars_to_fill=None,
            realized_status=None,
            r_multiple=Decimal("0"),
            bars_held_after_fill=0,
            opportunity_cost_r=entry.opportunity_cost_r,
            entry_adverse_selection_r=Decimal("0"),
            entry_termination_reason=entry.termination_reason,
            management_exit_reason="",
            management_valid=True,
            ambiguous=entry.ambiguous_pre_fill_bar,
        )

    start_index = max(0, (entry.bars_to_fill or 1) - 1) if policy.order_style is not OrderStyle.MARKET else 0
    remaining = scenario.future_candles[start_index:]
    adjusted = replace(scenario.candidate, entry_price=entry.fill_price)
    try:
        managed = evaluate_management_outcome(
            adjusted,
            remaining,
            policy.management,
            maximum_bars=policy.maximum_holding_bars,
            spread_pips=scenario.spread_pips,
            exit_slippage_pips=policy.exit_slippage_pips,
        )
    except ValueError as exc:
        # Policy geometry can become impossible after a different fill (for example a
        # fixed 1R partial beyond the structural target after a momentum-stop entry).
        # Count the signal in the denominator with zero realized R rather than dropping it.
        return PhaseDSignalOutcome(
            signal_key=scenario.signal_key,
            policy_name=policy.name,
            signal_time=signal_time,
            filled=True,
            fill_price=entry.fill_price,
            bars_to_fill=entry.bars_to_fill,
            realized_status=None,
            r_multiple=Decimal("0"),
            bars_held_after_fill=0,
            opportunity_cost_r=entry.opportunity_cost_r,
            entry_adverse_selection_r=entry.adverse_selection_r,
            entry_termination_reason=entry.termination_reason,
            management_exit_reason=f"invalid_management_geometry:{str(exc)[:160]}",
            management_valid=False,
            ambiguous=entry.ambiguous_pre_fill_bar,
        )
    return PhaseDSignalOutcome(
        signal_key=scenario.signal_key,
        policy_name=policy.name,
        signal_time=signal_time,
        filled=True,
        fill_price=entry.fill_price,
        bars_to_fill=entry.bars_to_fill,
        realized_status=managed.status,
        r_multiple=managed.r_multiple,
        bars_held_after_fill=managed.bars_held,
        opportunity_cost_r=entry.opportunity_cost_r,
        entry_adverse_selection_r=entry.adverse_selection_r,
        entry_termination_reason=entry.termination_reason,
        management_exit_reason=managed.exit_reason,
        management_valid=True,
        ambiguous=entry.ambiguous_pre_fill_bar or managed.ambiguous_bar,
    )


def compare_phase_d_policies(
    scenarios: Iterable[PhaseDScenario],
    *,
    baseline: PhaseDPolicy,
    variants: Iterable[PhaseDPolicy],
    confidence: Decimal = Decimal("0.90"),
    bootstrap_iterations: int = 2000,
    bootstrap_seed: int = 20260807,
) -> PhaseDComparisonReport:
    scenario_list = tuple(sorted(scenarios, key=_scenario_sort_key))
    variant_list = tuple(variants)
    if not scenario_list:
        raise ValueError("at least one Phase D scenario is required")
    if not variant_list:
        raise ValueError("at least one Phase D variant is required")
    if any(item.name == baseline.name for item in variant_list):
        raise ValueError("variant names must differ from the baseline")
    names = [item.name for item in variant_list]
    if len(names) != len(set(names)):
        raise ValueError("Phase D variant names must be unique")
    if not Decimal("0") < confidence < Decimal("1"):
        raise ValueError("confidence must be in (0,1)")
    if bootstrap_iterations < 100:
        raise ValueError("bootstrap_iterations must be at least 100")

    baseline_outcomes = tuple(evaluate_phase_d_policy(scenario, baseline) for scenario in scenario_list)
    baseline_report = summarize_phase_d_outcomes(baseline.name, baseline_outcomes)
    comparisons: list[PairedVariantComparison] = []
    for policy in variant_list:
        outcomes = tuple(evaluate_phase_d_policy(scenario, policy) for scenario in scenario_list)
        deltas = tuple(variant.r_multiple - control.r_multiple for control, variant in zip(baseline_outcomes, outcomes, strict=True))
        lower, upper = paired_bootstrap_mean_interval(
            deltas,
            confidence=confidence,
            iterations=bootstrap_iterations,
            seed=bootstrap_seed,
        )
        comparisons.append(
            PairedVariantComparison(
                policy=summarize_phase_d_outcomes(policy.name, outcomes),
                mean_delta_r_per_signal=sum(deltas, Decimal("0")) / Decimal(len(deltas)),
                lower_confidence_delta_r=lower,
                upper_confidence_delta_r=upper,
                paired_wins=sum(delta > 0 for delta in deltas),
                paired_losses=sum(delta < 0 for delta in deltas),
                paired_ties=sum(delta == 0 for delta in deltas),
            )
        )
    return PhaseDComparisonReport(
        baseline=baseline_report,
        variants=tuple(comparisons),
        scenario_count=len(scenario_list),
        confidence=confidence,
        bootstrap_iterations=bootstrap_iterations,
        bootstrap_seed=bootstrap_seed,
    )


def summarize_phase_d_outcomes(
    policy_name: str,
    outcomes: Iterable[PhaseDSignalOutcome],
) -> PhaseDPolicyReport:
    values = tuple(outcomes)
    if not values:
        raise ValueError("Phase D summary requires outcomes")
    count = Decimal(len(values))
    filled = [item for item in values if item.filled]
    valid_filled = [item for item in filled if item.management_valid]
    total_r = sum((item.r_multiple for item in values), Decimal("0"))
    return PhaseDPolicyReport(
        policy_name=policy_name,
        scenarios=len(values),
        fills=len(filled),
        fill_rate=Decimal(len(filled)) / count,
        management_valid=len(valid_filled),
        positive_signals=sum(item.r_multiple > 0 for item in values),
        total_r=total_r,
        average_r_per_signal=total_r / count,
        average_r_per_fill=(
            sum((item.r_multiple for item in filled), Decimal("0")) / Decimal(len(filled))
            if filled else Decimal("0")
        ),
        max_drawdown_r=_max_drawdown(tuple(item.r_multiple for item in values)),
        average_opportunity_cost_r=sum((item.opportunity_cost_r for item in values), Decimal("0")) / count,
        average_entry_adverse_selection_r=(
            sum((item.entry_adverse_selection_r for item in filled), Decimal("0")) / Decimal(len(filled))
            if filled else Decimal("0")
        ),
        invalidated_before_fill=sum(item.entry_termination_reason == "invalidated_before_fill" for item in values),
        target_missed_before_fill=sum(item.entry_termination_reason == "target_before_fill" for item in values),
        ambiguous_pre_fill=sum(item.entry_termination_reason == "ambiguous_pre_fill_bar" for item in values),
        expired_unfilled=sum(item.entry_termination_reason == "expired_unfilled" for item in values),
        invalid_management_geometry=sum(not item.management_valid for item in values),
        ambiguous_fraction=Decimal(sum(item.ambiguous for item in values)) / count,
    )


def paired_bootstrap_mean_interval(
    deltas: Iterable[Decimal],
    *,
    confidence: Decimal = Decimal("0.90"),
    iterations: int = 2000,
    seed: int = 20260807,
) -> tuple[Decimal, Decimal]:
    values = tuple(deltas)
    if not values:
        raise ValueError("paired bootstrap requires deltas")
    if not Decimal("0") < confidence < Decimal("1"):
        raise ValueError("confidence must be in (0,1)")
    if iterations < 100:
        raise ValueError("iterations must be at least 100")
    rng = random.Random(seed)
    sample_count = len(values)
    means: list[Decimal] = []
    for _ in range(iterations):
        total = Decimal("0")
        for _ in range(sample_count):
            total += values[rng.randrange(sample_count)]
        means.append(total / Decimal(sample_count))
    means.sort()
    alpha = (Decimal("1") - confidence) / Decimal("2")
    lower_index = min(iterations - 1, max(0, int(alpha * Decimal(iterations))))
    upper_index = min(iterations - 1, max(0, int((Decimal("1") - alpha) * Decimal(iterations)) - 1))
    return means[lower_index], means[upper_index]


def recommend_phase_d_variant(
    report: PhaseDComparisonReport,
    *,
    minimum_scenarios: int = 100,
    minimum_fill_rate: Decimal = Decimal("0.50"),
    maximum_drawdown_ratio: Decimal = Decimal("1.10"),
    minimum_lower_delta_r: Decimal = Decimal("0"),
) -> PhaseDResearchRecommendation:
    if minimum_scenarios < 2:
        raise ValueError("minimum_scenarios must be at least 2")
    if not Decimal("0") <= minimum_fill_rate <= Decimal("1"):
        raise ValueError("minimum_fill_rate must be in [0,1]")
    if maximum_drawdown_ratio <= 0:
        raise ValueError("maximum_drawdown_ratio must be positive")
    if report.scenario_count < minimum_scenarios:
        return PhaseDResearchRecommendation(
            False,
            None,
            Decimal("0"),
            (f"scenario_count {report.scenario_count} < {minimum_scenarios}",),
        )

    qualified: list[PairedVariantComparison] = []
    for item in report.variants:
        if item.lower_confidence_delta_r <= minimum_lower_delta_r:
            continue
        if item.policy.fill_rate < minimum_fill_rate:
            continue
        drawdown_limit = report.baseline.max_drawdown_r * maximum_drawdown_ratio
        if report.baseline.max_drawdown_r == 0:
            if item.policy.max_drawdown_r > 0:
                continue
        elif item.policy.max_drawdown_r > drawdown_limit:
            continue
        if item.policy.invalid_management_geometry > 0:
            continue
        qualified.append(item)
    if not qualified:
        return PhaseDResearchRecommendation(
            False,
            None,
            Decimal("0"),
            ("no variant has positive paired lower-bound expectancy with acceptable fill/drawdown/geometry",),
        )
    best = max(
        qualified,
        key=lambda item: (item.lower_confidence_delta_r, item.mean_delta_r_per_signal, -item.policy.max_drawdown_r),
    )
    return PhaseDResearchRecommendation(
        True,
        best.policy.policy_name,
        best.lower_confidence_delta_r,
        (
            "research candidate only; Practice authority still requires independent promotion evidence",
            f"paired lower-bound delta={best.lower_confidence_delta_r}",
        ),
    )


def _scenario_sort_key(scenario: PhaseDScenario) -> tuple[datetime, str]:
    signal_time = scenario.candidate.signal_time
    if not isinstance(signal_time, datetime):
        raise ValueError("Phase D scenarios require datetime signal_time")
    return signal_time, scenario.signal_key


def _max_drawdown(values: tuple[Decimal, ...]) -> Decimal:
    equity = Decimal("0")
    peak = Decimal("0")
    drawdown = Decimal("0")
    for value in values:
        equity += value
        peak = max(peak, equity)
        drawdown = max(drawdown, peak - equity)
    return drawdown
