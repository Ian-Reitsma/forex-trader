from decimal import Decimal

from forex_trader.adapters.synthetic import SyntheticMarketData
from forex_trader.domain.fundamentals import FundamentalBook
from forex_trader.domain.models import CurrencyFundamentals
from forex_trader.domain.strategy import SignalFusionPolicy
from forex_trader.research.backtest import run_walk_forward_backtest
from forex_trader.research.management import HALF_AT_ONE_R_RUNNER, STRUCTURAL_SINGLE_TARGET
from forex_trader.research.management_walk_forward import (
    compare_walk_forward_management_policies,
    run_walk_forward_management_backtest,
)


def fixture_data():  # type: ignore[no-untyped-def]
    market = SyntheticMarketData(seed=11, direction="long")
    lower = market.candles("EUR_USD", "M5", 260)
    higher = market.candles("EUR_USD", "H1", 220)
    fundamentals = FundamentalBook(
        [
            CurrencyFundamentals(
                "EUR",
                policy=Decimal("0.5"),
                confidence=Decimal("0.9"),
                as_of=market.anchor,
            ),
            CurrencyFundamentals(
                "USD",
                policy=Decimal("-0.5"),
                confidence=Decimal("0.9"),
                as_of=market.anchor,
            ),
        ]
    )
    return lower, higher, fundamentals


def test_structural_management_replay_matches_baseline_trade_stream() -> None:
    lower, higher, fundamentals = fixture_data()
    fusion = SignalFusionPolicy(minimum_score=Decimal("0.5"))
    baseline, _ = run_walk_forward_backtest(
        instrument="EUR_USD",
        lower_candles=lower,
        higher_candles=higher,
        fundamentals=fundamentals,
        fusion_policy=fusion,
        spread_pips=Decimal("0.5"),
    )
    managed, report = run_walk_forward_management_backtest(
        instrument="EUR_USD",
        lower_candles=lower,
        higher_candles=higher,
        fundamentals=fundamentals,
        fusion_policy=fusion,
        management_policy=STRUCTURAL_SINGLE_TARGET,
        spread_pips=Decimal("0.5"),
    )
    assert len(managed) == len(baseline)
    assert report.trades == len(baseline)
    assert [trade.status for trade in managed] == [trade.status for trade in baseline]
    assert [trade.bars_held for trade in managed] == [trade.bars_held for trade in baseline]
    assert [trade.r_multiple for trade in managed] == [trade.r_multiple for trade in baseline]


def test_management_comparison_replays_each_policy_sequentially() -> None:
    lower, higher, fundamentals = fixture_data()
    reports = compare_walk_forward_management_policies(
        instrument="EUR_USD",
        lower_candles=lower,
        higher_candles=higher,
        fundamentals=fundamentals,
        fusion_policy=SignalFusionPolicy(minimum_score=Decimal("0.5")),
        policies=[STRUCTURAL_SINGLE_TARGET, HALF_AT_ONE_R_RUNNER],
        spread_pips=Decimal("0.5"),
        exit_slippage_pips=Decimal("0.1"),
    )
    assert [report.policy_name for report in reports] == [
        STRUCTURAL_SINGLE_TARGET.name,
        HALF_AT_ONE_R_RUNNER.name,
    ]
    assert all(report.trades >= 0 for report in reports)


def test_management_walk_forward_validates_policy_and_cost_inputs() -> None:
    import pytest

    lower, higher, fundamentals = fixture_data()
    kwargs = dict(
        instrument="EUR_USD",
        lower_candles=lower,
        higher_candles=higher,
        fundamentals=fundamentals,
        fusion_policy=SignalFusionPolicy(minimum_score=Decimal("0.5")),
    )
    with pytest.raises(ValueError, match="at least one management policy"):
        compare_walk_forward_management_policies(**kwargs, policies=[])
    with pytest.raises(ValueError, match="maximum_holding_bars"):
        run_walk_forward_management_backtest(
            **kwargs,
            management_policy=STRUCTURAL_SINGLE_TARGET,
            maximum_holding_bars=0,
        )
    with pytest.raises(ValueError, match="costs"):
        run_walk_forward_management_backtest(
            **kwargs,
            management_policy=STRUCTURAL_SINGLE_TARGET,
            spread_pips=Decimal("-1"),
        )
