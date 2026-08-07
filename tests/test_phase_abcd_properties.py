from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

from hypothesis import given, strategies as st

from forex_trader.domain.context import DataQualitySnapshot, ReadinessPolicy
from forex_trader.research.advanced import OutcomeEstimate, expected_net_r

NOW = datetime(2026, 8, 7, 12, 0, tzinfo=UTC)


@given(st.decimals(min_value="0", max_value="20", places=3, allow_nan=False, allow_infinity=False))
def test_quote_readiness_is_monotone_in_quote_age(age: Decimal) -> None:
    policy = ReadinessPolicy(maximum_quote_age_seconds=Decimal("5"))
    result = policy.evaluate(
        DataQualitySnapshot(NOW, quote_age_seconds=age),
        require_calendar=False,
        require_fundamentals=False,
    )
    assert result.ready is (age <= Decimal("5"))


@given(
    st.decimals(min_value="0", max_value="1", places=3, allow_nan=False, allow_infinity=False),
    st.decimals(min_value="0", max_value="1", places=3, allow_nan=False, allow_infinity=False),
)
def test_expected_value_never_improves_when_execution_cost_increases(low_cost: Decimal, extra_cost: Decimal) -> None:
    estimate = OutcomeEstimate(
        p_target_before_stop=Decimal("0.55"),
        p_stop_before_target=Decimal("0.45"),
        expected_mfe_r=Decimal("1.5"),
        expected_mae_r=Decimal("0.8"),
        expected_holding_bars=Decimal("4"),
        sample_size=100,
        confidence_half_width=Decimal("0.1"),
        calibration_version="test",
    )
    base = expected_net_r(estimate, expected_gain_r=Decimal("1.5"), spread_cost_r=low_cost)
    more_expensive = expected_net_r(
        estimate,
        expected_gain_r=Decimal("1.5"),
        spread_cost_r=low_cost + extra_cost,
    )
    assert more_expensive <= base
