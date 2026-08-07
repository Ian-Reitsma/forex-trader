from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal
from enum import StrEnum

from forex_trader.domain.enums import DecisionDisposition, Direction
from forex_trader.domain.fundamentals import FundamentalBook
from forex_trader.domain.macro_history import PointInTimeFundamentalBook
from forex_trader.domain.models import Candle, Quote, TradeCandidate
from forex_trader.domain.strategy import SignalFusionPolicy
from forex_trader.domain.technicals import assess_technicals, pip_size


class OutcomeStatus(StrEnum):
    WIN = "win"
    LOSS = "loss"
    TIMEOUT = "timeout"


@dataclass(frozen=True, slots=True)
class BacktestTrade:
    instrument: str
    direction: Direction
    signal_time: datetime
    score: Decimal
    status: OutcomeStatus
    r_multiple: Decimal
    bars_held: int


@dataclass(frozen=True, slots=True)
class BacktestReport:
    trades: int
    wins: int
    losses: int
    timeouts: int
    win_rate: Decimal
    expectancy_r: Decimal
    profit_factor: Decimal | None
    max_drawdown_r: Decimal
    total_r: Decimal
    minimum_score: Decimal | None = None


def evaluate_candidate_outcome(
    candidate: TradeCandidate,
    future_candles: list[Candle],
    *,
    maximum_bars: int = 24,
    spread_pips: Decimal = Decimal("0"),
) -> BacktestTrade:
    """Evaluate a candidate using conservative intrabar assumptions.

    When stop and target are both touched in the same candle, the stop is assumed to
    have filled first. This avoids the optimistic ordering bias common in candle backtests.
    """
    if candidate.disposition is not DecisionDisposition.TRADE:
        raise ValueError("candidate must be tradeable")
    if candidate.entry_price is None or candidate.stop_loss is None or candidate.take_profit is None:
        raise ValueError("candidate must have entry, stop, and target")
    if maximum_bars < 1:
        raise ValueError("maximum_bars must be positive")
    if spread_pips < 0:
        raise ValueError("spread_pips cannot be negative")
    candles = [candle for candle in future_candles if candle.complete][:maximum_bars]
    if not candles:
        raise ValueError("at least one completed future candle is required")

    risk = abs(candidate.entry_price - candidate.stop_loss)
    if risk <= 0:
        raise ValueError("candidate stop distance must be positive")
    reward = abs(candidate.take_profit - candidate.entry_price)
    win_r = reward / risk

    half_spread = pip_size(candidate.instrument) * spread_pips / Decimal("2")
    for index, candle in enumerate(candles, start=1):
        if candidate.direction is Direction.LONG:
            executable_low = candle.low - half_spread
            executable_high = candle.high - half_spread
            stop_hit = executable_low <= candidate.stop_loss
            target_hit = executable_high >= candidate.take_profit
        elif candidate.direction is Direction.SHORT:
            executable_low = candle.low + half_spread
            executable_high = candle.high + half_spread
            stop_hit = executable_high >= candidate.stop_loss
            target_hit = executable_low <= candidate.take_profit
        else:
            raise ValueError("flat candidate cannot be backtested")
        if stop_hit:
            return BacktestTrade(
                candidate.instrument,
                candidate.direction,
                candidate.signal_time,
                candidate.score,
                OutcomeStatus.LOSS,
                Decimal("-1"),
                index,
            )
        if target_hit:
            return BacktestTrade(
                candidate.instrument,
                candidate.direction,
                candidate.signal_time,
                candidate.score,
                OutcomeStatus.WIN,
                win_r,
                index,
            )

    final_mid = candles[-1].close
    final_executable = (
        final_mid - half_spread
        if candidate.direction is Direction.LONG
        else final_mid + half_spread
    )
    directional_move = (
        final_executable - candidate.entry_price
        if candidate.direction is Direction.LONG
        else candidate.entry_price - final_executable
    )
    timeout_r = max(Decimal("-1"), min(win_r, directional_move / risk))
    return BacktestTrade(
        candidate.instrument,
        candidate.direction,
        candidate.signal_time,
        candidate.score,
        OutcomeStatus.TIMEOUT,
        timeout_r,
        len(candles),
    )


def summarize_trades(
    trades: list[BacktestTrade],
    *,
    minimum_score: Decimal | None = None,
) -> BacktestReport:
    selected = [trade for trade in trades if minimum_score is None or trade.score >= minimum_score]
    if not selected:
        return BacktestReport(
            trades=0,
            wins=0,
            losses=0,
            timeouts=0,
            win_rate=Decimal("0"),
            expectancy_r=Decimal("0"),
            profit_factor=None,
            max_drawdown_r=Decimal("0"),
            total_r=Decimal("0"),
            minimum_score=minimum_score,
        )

    wins = sum(trade.status is OutcomeStatus.WIN for trade in selected)
    losses = sum(trade.status is OutcomeStatus.LOSS for trade in selected)
    timeouts = len(selected) - wins - losses
    total_r = sum((trade.r_multiple for trade in selected), Decimal("0"))
    positive_r = sum((trade.r_multiple for trade in selected if trade.r_multiple > 0), Decimal("0"))
    negative_r = -sum((trade.r_multiple for trade in selected if trade.r_multiple < 0), Decimal("0"))
    profit_factor = None if negative_r == 0 else positive_r / negative_r

    equity = Decimal("0")
    peak = Decimal("0")
    max_drawdown = Decimal("0")
    for trade in selected:
        equity += trade.r_multiple
        peak = max(peak, equity)
        max_drawdown = max(max_drawdown, peak - equity)

    return BacktestReport(
        trades=len(selected),
        wins=wins,
        losses=losses,
        timeouts=timeouts,
        win_rate=Decimal(wins) / Decimal(len(selected)),
        expectancy_r=total_r / Decimal(len(selected)),
        profit_factor=profit_factor,
        max_drawdown_r=max_drawdown,
        total_r=total_r,
        minimum_score=minimum_score,
    )


def optimize_score_threshold(
    trades: list[BacktestTrade],
    *,
    thresholds: tuple[Decimal, ...] = (
        Decimal("0.55"),
        Decimal("0.60"),
        Decimal("0.65"),
        Decimal("0.70"),
        Decimal("0.75"),
        Decimal("0.80"),
    ),
    minimum_trades: int = 20,
) -> BacktestReport:
    """Select a threshold by expectancy, then win rate and drawdown.

    This helper is intended for a training fold only. The selected threshold must be
    evaluated on a later untouched validation fold before it is adopted.
    """
    if minimum_trades < 1:
        raise ValueError("minimum_trades must be positive")
    reports = [summarize_trades(trades, minimum_score=threshold) for threshold in thresholds]
    eligible = [report for report in reports if report.trades >= minimum_trades]
    if not eligible:
        raise ValueError("no threshold has enough trades")
    return max(
        eligible,
        key=lambda report: (
            report.expectancy_r,
            report.win_rate,
            -report.max_drawdown_r,
            report.trades,
        ),
    )


def run_walk_forward_backtest(
    *,
    instrument: str,
    lower_candles: list[Candle],
    higher_candles: list[Candle],
    fundamentals: FundamentalBook | PointInTimeFundamentalBook,
    fusion_policy: SignalFusionPolicy,
    spread_pips: Decimal = Decimal("1.0"),
    maximum_holding_bars: int = 24,
    lower_timeframe: timedelta = timedelta(minutes=5),
    higher_timeframe: timedelta = timedelta(hours=1),
) -> tuple[list[BacktestTrade], BacktestReport]:
    """Replay completed candles without using future bars in signal construction.

    The spread is applied to the synthetic executable quote. Pass a
    PointInTimeFundamentalBook to guarantee that each decision sees only macro/news
    observations available at that historical timestamp. A plain FundamentalBook is
    supported for technical-only diagnostics and controlled tests.
    """
    lower = sorted((c for c in lower_candles if c.complete), key=lambda candle: candle.time)
    higher = sorted((c for c in higher_candles if c.complete), key=lambda candle: candle.time)
    if len(lower) < 62 or len(higher) < 60:
        raise ValueError("walk-forward backtest requires at least 62 lower and 60 higher candles")
    if spread_pips < 0:
        raise ValueError("spread_pips cannot be negative")
    if lower_timeframe <= timedelta(0) or higher_timeframe <= timedelta(0):
        raise ValueError("timeframe durations must be positive")

    half_spread = pip_size(instrument) * spread_pips / Decimal("2")
    results: list[BacktestTrade] = []
    index = 59
    while index < len(lower) - 1:
        signal_candle = lower[index]
        decision_time = signal_candle.time + lower_timeframe
        higher_available = [
            candle
            for candle in higher
            if candle.time + higher_timeframe <= decision_time
        ]
        if len(higher_available) < 60:
            index += 1
            continue
        technical = assess_technicals(
            instrument,
            lower[max(0, index - 199) : index + 1],
            higher_available[-200:],
        )
        quote = Quote(
            instrument=instrument,
            bid=signal_candle.close - half_spread,
            ask=signal_candle.close + half_spread,
            time=decision_time + timedelta(seconds=1),
        )
        fundamental = fundamentals.assess_pair(instrument, as_of=quote.time)
        candidate = fusion_policy.evaluate(technical, fundamental, quote)
        if candidate.disposition is DecisionDisposition.TRADE:
            future = lower[index + 1 : index + 1 + maximum_holding_bars]
            if not future:
                break
            outcome = evaluate_candidate_outcome(
                candidate,
                future,
                maximum_bars=maximum_holding_bars,
                spread_pips=spread_pips,
            )
            results.append(outcome)
            index += max(1, outcome.bars_held)
        else:
            index += 1
    return results, summarize_trades(results)
