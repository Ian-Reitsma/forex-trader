from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import uuid4

from forex_trader.domain.enums import DecisionDisposition, Direction
from forex_trader.domain.models import Candle, TradeCandidate
from forex_trader.research.management import HALF_AT_ONE_R_RUNNER, STRUCTURAL_SINGLE_TARGET
from forex_trader.research.order_types import OrderStyle, evaluate_entry_style
from forex_trader.research.phase_d import (
    PairedVariantComparison,
    PhaseDComparisonReport,
    PhaseDPolicy,
    PhaseDPolicyReport,
    PhaseDScenario,
    compare_phase_d_policies,
    evaluate_phase_d_policy,
    paired_bootstrap_mean_interval,
    recommend_phase_d_variant,
)

NOW = datetime(2026, 8, 7, 12, 0, tzinfo=UTC)


def candidate(*, target: str = "1.1030") -> TradeCandidate:
    return TradeCandidate(
        uuid4(),
        "EUR_USD",
        Direction.LONG,
        DecisionDisposition.TRADE,
        Decimal("0.8"),
        Decimal("1.1000"),
        Decimal("1.0990"),
        Decimal(target),
        Decimal("0.8"),
        Decimal("0.6"),
        (),
        signal_time=NOW,
    )


def candle(index: int, *, open_: str, high: str, low: str, close: str) -> Candle:
    return Candle(
        NOW + timedelta(minutes=5 * index),
        Decimal(open_),
        Decimal(high),
        Decimal(low),
        Decimal(close),
    )


def test_pending_pullback_entry_does_not_fill_after_target_is_already_reached() -> None:
    path = (
        candle(1, open_="1.1000", high="1.1032", low="1.1000", close="1.1028"),
        candle(2, open_="1.1028", high="1.1031", low="1.0996", close="1.1002"),
    )
    result = evaluate_entry_style(candidate(), path, OrderStyle.LIMIT, offset_r=Decimal("0.25"))
    assert result.filled is False
    assert result.termination_reason == "target_before_fill"
    assert result.opportunity_cost_r >= Decimal("3")


def test_same_bar_pullback_trigger_and_invalidation_is_not_granted_favorable_ordering() -> None:
    path = (candle(1, open_="1.1000", high="1.1004", low="1.0988", close="1.0998"),)
    result = evaluate_entry_style(candidate(), path, OrderStyle.LIMIT, offset_r=Decimal("0.25"))
    assert result.filled is False
    assert result.ambiguous_pre_fill_bar is True
    assert result.termination_reason == "ambiguous_pre_fill_bar"


def test_paired_comparison_counts_missed_limit_as_zero_r_in_same_signal_denominator() -> None:
    pullback_then_target = PhaseDScenario(
        "pullback",
        candidate(),
        (
            candle(1, open_="1.1000", high="1.1004", low="1.0997", close="1.1002"),
            candle(2, open_="1.1002", high="1.1032", low="1.1000", close="1.1029"),
        ),
    )
    straight_to_target = PhaseDScenario(
        "straight",
        candidate(),
        (candle(1, open_="1.1000", high="1.1032", low="1.1000", close="1.1029"),),
    )
    baseline = PhaseDPolicy(
        "market",
        OrderStyle.MARKET,
        entry_slippage_pips=Decimal("0"),
        exit_slippage_pips=Decimal("0"),
    )
    limit = PhaseDPolicy(
        "limit-025",
        OrderStyle.LIMIT,
        offset_r=Decimal("0.25"),
        entry_slippage_pips=Decimal("0"),
        exit_slippage_pips=Decimal("0"),
    )
    report = compare_phase_d_policies(
        [pullback_then_target, straight_to_target],
        baseline=baseline,
        variants=[limit],
        bootstrap_iterations=200,
    )
    variant = report.variants[0]
    assert report.baseline.scenarios == 2
    assert variant.policy.scenarios == 2
    assert variant.policy.fills == 1
    assert variant.policy.target_missed_before_fill == 1
    assert variant.policy.average_r_per_signal == variant.policy.total_r / Decimal("2")
    assert variant.paired_wins + variant.paired_losses + variant.paired_ties == 2


def test_momentum_entry_that_makes_fixed_partial_geometry_impossible_is_not_dropped() -> None:
    scenario = PhaseDScenario(
        "momentum",
        candidate(),
        (
            candle(1, open_="1.1000", high="1.1022", low="1.1000", close="1.1021"),
            candle(2, open_="1.1021", high="1.1031", low="1.1018", close="1.1028"),
        ),
    )
    policy = PhaseDPolicy(
        "stop-2r-half",
        OrderStyle.STOP,
        offset_r=Decimal("2"),
        entry_slippage_pips=Decimal("0"),
        exit_slippage_pips=Decimal("0"),
        management=HALF_AT_ONE_R_RUNNER,
    )
    result = evaluate_phase_d_policy(scenario, policy)
    assert result.filled is True
    assert result.management_valid is False
    assert result.r_multiple == 0
    assert result.management_exit_reason.startswith("invalid_management_geometry")


def test_paired_bootstrap_is_deterministic_and_preserves_constant_delta() -> None:
    lower, upper = paired_bootstrap_mean_interval(
        [Decimal("0.25")] * 20,
        confidence=Decimal("0.90"),
        iterations=200,
        seed=7,
    )
    assert lower == Decimal("0.25")
    assert upper == Decimal("0.25")


def _report(name: str, *, fill_rate: str, drawdown: str, average: str) -> PhaseDPolicyReport:
    return PhaseDPolicyReport(
        policy_name=name,
        scenarios=120,
        fills=int(Decimal(fill_rate) * Decimal("120")),
        fill_rate=Decimal(fill_rate),
        management_valid=int(Decimal(fill_rate) * Decimal("120")),
        positive_signals=60,
        total_r=Decimal(average) * Decimal("120"),
        average_r_per_signal=Decimal(average),
        average_r_per_fill=Decimal(average),
        max_drawdown_r=Decimal(drawdown),
        average_opportunity_cost_r=Decimal("0.1"),
        average_entry_adverse_selection_r=Decimal("0.05"),
        invalidated_before_fill=0,
        target_missed_before_fill=0,
        ambiguous_pre_fill=0,
        expired_unfilled=0,
        invalid_management_geometry=0,
        ambiguous_fraction=Decimal("0"),
    )


def test_research_recommendation_requires_positive_paired_lower_bound_fill_and_drawdown() -> None:
    baseline = _report("market", fill_rate="1", drawdown="5", average="0.10")
    good = PairedVariantComparison(
        _report("limit", fill_rate="0.75", drawdown="4", average="0.20"),
        Decimal("0.10"),
        Decimal("0.03"),
        Decimal("0.17"),
        70,
        30,
        20,
    )
    lucky = PairedVariantComparison(
        _report("stop", fill_rate="0.9", drawdown="4", average="0.30"),
        Decimal("0.20"),
        Decimal("-0.02"),
        Decimal("0.42"),
        75,
        25,
        20,
    )
    report = PhaseDComparisonReport(
        baseline=baseline,
        variants=(good, lucky),
        scenario_count=120,
        confidence=Decimal("0.90"),
        bootstrap_iterations=2000,
        bootstrap_seed=7,
    )
    recommendation = recommend_phase_d_variant(report, minimum_scenarios=100)
    assert recommendation.eligible is True
    assert recommendation.policy_name == "limit"
    assert recommendation.lower_confidence_delta_r == Decimal("0.03")


def test_research_recommendation_refuses_small_sample() -> None:
    report = PhaseDComparisonReport(
        baseline=_report("market", fill_rate="1", drawdown="5", average="0.10"),
        variants=(),
        scenario_count=20,
        confidence=Decimal("0.90"),
        bootstrap_iterations=2000,
        bootstrap_seed=7,
    )
    recommendation = recommend_phase_d_variant(report, minimum_scenarios=100)
    assert recommendation.eligible is False
    assert recommendation.policy_name is None
    assert "scenario_count" in recommendation.reasons[0]
