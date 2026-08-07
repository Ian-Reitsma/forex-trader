from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import uuid4

import pytest

from forex_trader.domain.enums import DecisionDisposition, Direction
from forex_trader.domain.models import Candle, TradeCandidate
from forex_trader.research.backtest import (
    BacktestTrade,
    OutcomeStatus,
    evaluate_candidate_outcome,
    optimize_score_threshold,
    summarize_trades,
)


def candidate(direction: Direction = Direction.LONG, score: str = "0.75") -> TradeCandidate:
    return TradeCandidate(
        candidate_id=uuid4(),
        instrument="EUR_USD",
        direction=direction,
        disposition=DecisionDisposition.TRADE,
        score=Decimal(score),
        entry_price=Decimal("1.1000"),
        stop_loss=Decimal("1.0990") if direction is Direction.LONG else Decimal("1.1010"),
        take_profit=Decimal("1.1020") if direction is Direction.LONG else Decimal("1.0980"),
        technical_score=Decimal("0.8"),
        fundamental_score=Decimal("0.6"),
        reasons=(),
    )


def candle(index: int, low: str, high: str, close: str = "1.1000") -> Candle:
    return Candle(
        datetime(2026, 1, 1, tzinfo=UTC) + timedelta(minutes=5 * index),
        Decimal("1.1000"),
        Decimal(high),
        Decimal(low),
        Decimal(close),
    )


def test_backtest_uses_conservative_same_bar_ordering() -> None:
    result = evaluate_candidate_outcome(
        candidate(),
        [candle(1, "1.0985", "1.1025")],
    )
    assert result.status is OutcomeStatus.LOSS
    assert result.r_multiple == Decimal("-1")


def test_backtest_win_timeout_and_summary() -> None:
    win = evaluate_candidate_outcome(candidate(), [candle(1, "1.0995", "1.1021")])
    timeout = evaluate_candidate_outcome(candidate(score="0.65"), [candle(2, "1.0995", "1.1005", "1.1004")])
    report = summarize_trades([win, timeout])
    assert win.status is OutcomeStatus.WIN
    assert win.r_multiple == Decimal("2")
    assert timeout.status is OutcomeStatus.TIMEOUT
    assert report.trades == 2
    assert report.total_r > 0
    assert report.max_drawdown_r == 0


def test_threshold_optimizer_prefers_expectancy_with_minimum_sample() -> None:
    trades = [
        BacktestTrade("EUR_USD", Direction.LONG, datetime.now(UTC), Decimal("0.60"), OutcomeStatus.LOSS, Decimal("-1"), 1)
        for _ in range(20)
    ]
    trades.extend(
        BacktestTrade("EUR_USD", Direction.LONG, datetime.now(UTC), Decimal("0.80"), OutcomeStatus.WIN, Decimal("2"), 2)
        for _ in range(20)
    )
    report = optimize_score_threshold(
        trades,
        thresholds=(Decimal("0.60"), Decimal("0.75")),
        minimum_trades=20,
    )
    assert report.minimum_score == Decimal("0.75")
    assert report.win_rate == Decimal("1")


def test_threshold_optimizer_rejects_tiny_samples() -> None:
    with pytest.raises(ValueError, match="enough trades"):
        optimize_score_threshold([], minimum_trades=2)


def test_walk_forward_replay_uses_only_available_candles() -> None:
    from dataclasses import replace

    from forex_trader.adapters.synthetic import SyntheticMarketData
    from forex_trader.domain.fundamentals import FundamentalBook
    from forex_trader.domain.models import CurrencyFundamentals, Quote
    from forex_trader.domain.strategy import SignalFusionPolicy
    from forex_trader.domain.technicals import assess_technicals
    from forex_trader.research.backtest import run_walk_forward_backtest

    market = SyntheticMarketData(seed=17, direction="long")
    lower = market.candles("EUR_USD", "M5", 200)
    higher_raw = market.candles("EUR_USD", "H1", 200)
    offset = lower[-1].time - higher_raw[-1].time
    higher = [replace(item, time=item.time + offset) for item in higher_raw]
    technical = assess_technicals("EUR_USD", lower, higher)
    assert technical.take_profit_reference is not None
    assert technical.stop_reference is not None
    future = Candle(
        lower[-1].time + timedelta(minutes=5),
        lower[-1].close,
        technical.take_profit_reference + Decimal("0.0002"),
        max(technical.stop_reference + Decimal("0.0001"), lower[-1].close - Decimal("0.0001")),
        technical.take_profit_reference,
    )
    fundamentals = FundamentalBook(
        [
            CurrencyFundamentals("EUR", policy=Decimal("0.4"), confidence=Decimal("0.9")),
            CurrencyFundamentals("USD", policy=Decimal("-0.3"), confidence=Decimal("0.9")),
        ]
    )
    trades, report = run_walk_forward_backtest(
        instrument="EUR_USD",
        lower_candles=[*lower, future],
        higher_candles=higher,
        fundamentals=fundamentals,
        fusion_policy=SignalFusionPolicy(minimum_score=Decimal("0.5")),
        spread_pips=Decimal("0.5"),
    )
    assert len(trades) == 1
    assert report.wins == 1


def test_backtest_applies_spread_to_exit_barriers() -> None:
    barely_hits_mid_target = candle(1, "1.0995", "1.1020", "1.1019")
    no_spread = evaluate_candidate_outcome(candidate(), [barely_hits_mid_target])
    with_spread = evaluate_candidate_outcome(
        candidate(),
        [barely_hits_mid_target],
        spread_pips=Decimal("1.0"),
    )
    assert no_spread.status is OutcomeStatus.WIN
    assert with_spread.status is OutcomeStatus.TIMEOUT
    assert with_spread.r_multiple < no_spread.r_multiple
