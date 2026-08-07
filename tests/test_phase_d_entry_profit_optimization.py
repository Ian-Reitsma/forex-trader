from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import uuid4

import pytest

from forex_trader.domain.enums import DecisionDisposition, Direction
from forex_trader.domain.models import Candle, TradeCandidate
from forex_trader.research.backtest import BacktestTrade, OutcomeStatus
from forex_trader.research.optimization import confidence_adjusted_thresholds, select_confidence_adjusted_threshold
from forex_trader.research.order_types import OrderStyle, compare_entry_styles, evaluate_entry_style

NOW = datetime(2026, 8, 7, 12, 0, tzinfo=UTC)


def candidate() -> TradeCandidate:
    return TradeCandidate(
        uuid4(),
        "EUR_USD",
        Direction.LONG,
        DecisionDisposition.TRADE,
        Decimal("0.8"),
        Decimal("1.1000"),
        Decimal("1.0990"),
        Decimal("1.1030"),
        Decimal("0.8"),
        Decimal("0.6"),
        (),
        signal_time=NOW,
    )


def candles() -> tuple[Candle, ...]:
    return (
        Candle(NOW + timedelta(minutes=5), Decimal("1.1000"), Decimal("1.1008"), Decimal("1.0996"), Decimal("1.1006")),
        Candle(NOW + timedelta(minutes=10), Decimal("1.1006"), Decimal("1.1018"), Decimal("1.1002"), Decimal("1.1015")),
        Candle(NOW + timedelta(minutes=15), Decimal("1.1015"), Decimal("1.1032"), Decimal("1.1010"), Decimal("1.1028")),
    )


def test_entry_styles_measure_fill_delay_and_opportunity_cost() -> None:
    market = evaluate_entry_style(candidate(), candles(), OrderStyle.MARKET)
    assert market.filled and market.bars_to_fill == 0
    limit = evaluate_entry_style(candidate(), candles(), OrderStyle.LIMIT, offset_r=Decimal("0.25"))
    assert limit.filled and limit.fill_price == Decimal("1.09975")
    mit = evaluate_entry_style(candidate(), candles(), OrderStyle.MARKET_IF_TOUCHED, offset_r=Decimal("0.25"), slippage_pips=Decimal("0.1"))
    assert mit.filled and mit.fill_price > Decimal("1.09975")
    stop = evaluate_entry_style(candidate(), candles(), OrderStyle.STOP, offset_r=Decimal("0.25"))
    assert stop.filled and stop.fill_price == Decimal("1.10025")

    reports = compare_entry_styles([(candidate(), candles())])
    assert {item.style for item in reports} == set(OrderStyle)
    assert next(item for item in reports if item.style is OrderStyle.MARKET).fill_rate == Decimal("1")


def test_entry_style_handles_missed_limit_and_invalid_inputs() -> None:
    far = evaluate_entry_style(candidate(), candles(), OrderStyle.LIMIT, offset_r=Decimal("2"))
    assert not far.filled
    assert far.opportunity_cost_r > 0
    with pytest.raises(ValueError):
        compare_entry_styles([])
    with pytest.raises(ValueError):
        evaluate_entry_style(candidate(), [], OrderStyle.MARKET)
    with pytest.raises(ValueError):
        evaluate_entry_style(candidate(), candles(), OrderStyle.MARKET, offset_r=Decimal("-1"))


def backtest_trade(score: str, r: str, *, cost: str = "0.05") -> BacktestTrade:
    value = Decimal(r)
    return BacktestTrade(
        "EUR_USD",
        Direction.LONG,
        NOW,
        Decimal(score),
        OutcomeStatus.WIN if value > 0 else OutcomeStatus.LOSS,
        value,
        3,
        estimated_cost_r=Decimal(cost),
    )


def test_confidence_adjusted_optimizer_prefers_repeatable_expectancy() -> None:
    trades: list[BacktestTrade] = []
    for index in range(40):
        trades.append(backtest_trade("0.65", "0.8" if index % 2 == 0 else "-0.4"))
    for index in range(20):
        trades.append(backtest_trade("0.85", "3" if index < 8 else "-1"))
    results = confidence_adjusted_thresholds(
        trades,
        thresholds=(Decimal("0.60"), Decimal("0.80")),
        minimum_trades=15,
    )
    assert len(results) == 2
    selected = select_confidence_adjusted_threshold(
        trades,
        thresholds=(Decimal("0.60"), Decimal("0.80")),
        minimum_trades=15,
    )
    assert selected.report.trades >= 15
    assert selected.lower_confidence_expectancy_r <= selected.report.expectancy_r


def test_confidence_optimizer_rejects_undersampled_search() -> None:
    trades = [backtest_trade("0.8", "1"), backtest_trade("0.8", "-1")]
    with pytest.raises(ValueError):
        select_confidence_adjusted_threshold(trades, thresholds=(Decimal("0.8"),), minimum_trades=3)
    with pytest.raises(ValueError):
        confidence_adjusted_thresholds(trades, thresholds=(Decimal("0.8"),), minimum_trades=1)
    with pytest.raises(ValueError):
        confidence_adjusted_thresholds(trades, thresholds=(Decimal("0.8"),), minimum_trades=2, confidence_z=Decimal("-1"))
