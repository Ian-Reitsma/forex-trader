from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal
from enum import StrEnum
from typing import Callable

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
    exit_reason: str = ""
    entry_fill: Decimal | None = None
    exit_fill: Decimal | None = None
    ambiguous_bar: bool = False
    maximum_favorable_r: Decimal = Decimal("0")
    maximum_adverse_r: Decimal = Decimal("0")
    estimated_cost_r: Decimal = Decimal("0")


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
    ambiguous_trades: int = 0
    ambiguous_fraction: Decimal = Decimal("0")
    average_mfe_r: Decimal = Decimal("0")
    average_mae_r: Decimal = Decimal("0")
    average_cost_r: Decimal = Decimal("0")


SpreadModel = Callable[[Candle, int], Decimal]


def evaluate_candidate_outcome(
    candidate: TradeCandidate,
    future_candles: list[Candle],
    *,
    maximum_bars: int = 24,
    spread_pips: Decimal = Decimal("0"),
    spread_model: SpreadModel | None = None,
    entry_slippage_pips: Decimal = Decimal("0"),
    exit_slippage_pips: Decimal = Decimal("0"),
    entry_delay_bars: int = 0,
) -> BacktestTrade:
    """Evaluate an executable candidate with conservative candle-path assumptions.

    Limitations are explicit: candle OHLC cannot reveal exact bid/ask tick ordering. If
    stop and target are touched in one bar we assume the stop first and flag the trade
    ambiguous. Gap-through stops fill at the executable opening price, so losses may be
    worse than -1R. Optional spread/slippage/delay parameters support stress testing.
    """
    if candidate.disposition is not DecisionDisposition.TRADE:
        raise ValueError("candidate must be tradeable")
    if candidate.entry_price is None or candidate.stop_loss is None or candidate.take_profit is None:
        raise ValueError("candidate must have entry, stop, and target")
    if maximum_bars < 1:
        raise ValueError("maximum_bars must be positive")
    if spread_pips < 0 or entry_slippage_pips < 0 or exit_slippage_pips < 0:
        raise ValueError("execution costs cannot be negative")
    if entry_delay_bars < 0:
        raise ValueError("entry_delay_bars cannot be negative")
    candles = [candle for candle in future_candles if candle.complete][:maximum_bars]
    if not candles or entry_delay_bars >= len(candles):
        raise ValueError("at least one completed executable future candle is required")

    pip = pip_size(candidate.instrument)
    delayed = candles[entry_delay_bars:]
    initial_spread = _spread_for(delayed[0], entry_delay_bars + 1, spread_pips, spread_model)
    half_initial = pip * initial_spread / Decimal("2")
    adverse_entry = pip * entry_slippage_pips
    # With zero delay the strategy quote is the intended fill and slippage adjusts it.
    # A delayed entry uses the next executable open to model computation/network latency.
    if entry_delay_bars == 0:
        entry_fill = candidate.entry_price + adverse_entry if candidate.direction is Direction.LONG else candidate.entry_price - adverse_entry
    elif candidate.direction is Direction.LONG:
        entry_fill = delayed[0].open + half_initial + adverse_entry
    else:
        entry_fill = delayed[0].open - half_initial - adverse_entry

    if candidate.direction is Direction.LONG and not candidate.stop_loss < entry_fill < candidate.take_profit:
        return _late_entry(candidate, entry_fill, entry_delay_bars + 1)
    if candidate.direction is Direction.SHORT and not candidate.take_profit < entry_fill < candidate.stop_loss:
        return _late_entry(candidate, entry_fill, entry_delay_bars + 1)

    risk = abs(entry_fill - candidate.stop_loss)
    reward = abs(candidate.take_profit - entry_fill)
    if risk <= 0:
        raise ValueError("candidate stop distance must be positive")
    entry_cost_r = adverse_entry / risk
    max_favorable = Decimal("0")
    max_adverse = Decimal("0")

    for relative_index, candle in enumerate(delayed, start=1):
        original_index = relative_index + entry_delay_bars
        current_spread = _spread_for(candle, original_index, spread_pips, spread_model)
        half_spread = pip * current_spread / Decimal("2")
        adverse_exit = pip * exit_slippage_pips
        if candidate.direction is Direction.LONG:
            executable_open = candle.open - half_spread
            executable_low = candle.low - half_spread
            executable_high = candle.high - half_spread
            favorable_r = max(Decimal("0"), (executable_high - entry_fill) / risk)
            adverse_r = max(Decimal("0"), (entry_fill - executable_low) / risk)
            stop_hit = executable_low <= candidate.stop_loss
            target_hit = executable_high >= candidate.take_profit
            max_favorable = max(max_favorable, favorable_r)
            max_adverse = max(max_adverse, adverse_r)
            if stop_hit:
                gap_fill = min(candidate.stop_loss, executable_open) - adverse_exit
                realized = (gap_fill - entry_fill) / risk
                return BacktestTrade(
                    candidate.instrument,
                    candidate.direction,
                    candidate.signal_time,
                    candidate.score,
                    OutcomeStatus.LOSS,
                    realized,
                    original_index,
                    exit_reason="gap_stop" if executable_open < candidate.stop_loss else "stop",
                    entry_fill=entry_fill,
                    exit_fill=gap_fill,
                    ambiguous_bar=target_hit,
                    maximum_favorable_r=max_favorable,
                    maximum_adverse_r=max_adverse,
                    estimated_cost_r=entry_cost_r + adverse_exit / risk,
                )
            if target_hit:
                fill = candidate.take_profit - adverse_exit
                realized = (fill - entry_fill) / risk
                return BacktestTrade(
                    candidate.instrument,
                    candidate.direction,
                    candidate.signal_time,
                    candidate.score,
                    OutcomeStatus.WIN,
                    realized,
                    original_index,
                    exit_reason="target",
                    entry_fill=entry_fill,
                    exit_fill=fill,
                    maximum_favorable_r=max_favorable,
                    maximum_adverse_r=max_adverse,
                    estimated_cost_r=entry_cost_r + adverse_exit / risk,
                )
        elif candidate.direction is Direction.SHORT:
            executable_open = candle.open + half_spread
            executable_low = candle.low + half_spread
            executable_high = candle.high + half_spread
            favorable_r = max(Decimal("0"), (entry_fill - executable_low) / risk)
            adverse_r = max(Decimal("0"), (executable_high - entry_fill) / risk)
            stop_hit = executable_high >= candidate.stop_loss
            target_hit = executable_low <= candidate.take_profit
            max_favorable = max(max_favorable, favorable_r)
            max_adverse = max(max_adverse, adverse_r)
            if stop_hit:
                gap_fill = max(candidate.stop_loss, executable_open) + adverse_exit
                realized = (entry_fill - gap_fill) / risk
                return BacktestTrade(
                    candidate.instrument,
                    candidate.direction,
                    candidate.signal_time,
                    candidate.score,
                    OutcomeStatus.LOSS,
                    realized,
                    original_index,
                    exit_reason="gap_stop" if executable_open > candidate.stop_loss else "stop",
                    entry_fill=entry_fill,
                    exit_fill=gap_fill,
                    ambiguous_bar=target_hit,
                    maximum_favorable_r=max_favorable,
                    maximum_adverse_r=max_adverse,
                    estimated_cost_r=entry_cost_r + adverse_exit / risk,
                )
            if target_hit:
                fill = candidate.take_profit + adverse_exit
                realized = (entry_fill - fill) / risk
                return BacktestTrade(
                    candidate.instrument,
                    candidate.direction,
                    candidate.signal_time,
                    candidate.score,
                    OutcomeStatus.WIN,
                    realized,
                    original_index,
                    exit_reason="target",
                    entry_fill=entry_fill,
                    exit_fill=fill,
                    maximum_favorable_r=max_favorable,
                    maximum_adverse_r=max_adverse,
                    estimated_cost_r=entry_cost_r + adverse_exit / risk,
                )
        else:
            raise ValueError("flat candidate cannot be backtested")

    final = delayed[-1]
    final_spread = _spread_for(final, len(candles), spread_pips, spread_model)
    half_final = pip * final_spread / Decimal("2")
    adverse_exit = pip * exit_slippage_pips
    final_executable = (
        final.close - half_final - adverse_exit
        if candidate.direction is Direction.LONG
        else final.close + half_final + adverse_exit
    )
    directional_move = final_executable - entry_fill if candidate.direction is Direction.LONG else entry_fill - final_executable
    timeout_r = directional_move / risk
    return BacktestTrade(
        candidate.instrument,
        candidate.direction,
        candidate.signal_time,
        candidate.score,
        OutcomeStatus.TIMEOUT,
        timeout_r,
        len(candles),
        exit_reason="time_stop",
        entry_fill=entry_fill,
        exit_fill=final_executable,
        maximum_favorable_r=max_favorable,
        maximum_adverse_r=max_adverse,
        estimated_cost_r=entry_cost_r + adverse_exit / risk,
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
    ambiguous = sum(trade.ambiguous_bar for trade in selected)

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
        ambiguous_trades=ambiguous,
        ambiguous_fraction=Decimal(ambiguous) / Decimal(len(selected)),
        average_mfe_r=sum((trade.maximum_favorable_r for trade in selected), Decimal("0")) / Decimal(len(selected)),
        average_mae_r=sum((trade.maximum_adverse_r for trade in selected), Decimal("0")) / Decimal(len(selected)),
        average_cost_r=sum((trade.estimated_cost_r for trade in selected), Decimal("0")) / Decimal(len(selected)),
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
    if minimum_trades < 1:
        raise ValueError("minimum_trades must be positive")
    reports = [summarize_trades(trades, minimum_score=threshold) for threshold in thresholds]
    eligible = [report for report in reports if report.trades >= minimum_trades]
    if not eligible:
        raise ValueError("no threshold has enough trades")
    return max(eligible, key=lambda report: (report.expectancy_r, report.win_rate, -report.max_drawdown_r, report.trades))


def run_walk_forward_backtest(
    *,
    instrument: str,
    lower_candles: list[Candle],
    higher_candles: list[Candle],
    fundamentals: FundamentalBook | PointInTimeFundamentalBook,
    fusion_policy: SignalFusionPolicy,
    spread_pips: Decimal = Decimal("1.0"),
    spread_model: SpreadModel | None = None,
    entry_slippage_pips: Decimal = Decimal("0"),
    exit_slippage_pips: Decimal = Decimal("0"),
    entry_delay_bars: int = 0,
    maximum_holding_bars: int = 24,
    lower_timeframe: timedelta = timedelta(minutes=5),
    higher_timeframe: timedelta = timedelta(hours=1),
) -> tuple[list[BacktestTrade], BacktestReport]:
    """Replay completed candles with point-in-time features and execution stress hooks.

    Midpoint candles remain a data limitation; real historical bid/ask/tick feeds should
    replace `spread_model` approximations before any profitability claim is made.
    """
    lower = sorted((c for c in lower_candles if c.complete), key=lambda candle: candle.time)
    higher = sorted((c for c in higher_candles if c.complete), key=lambda candle: candle.time)
    if len(lower) < 82 or len(higher) < 60:
        raise ValueError("walk-forward backtest requires at least 82 lower and 60 higher candles")
    if spread_pips < 0:
        raise ValueError("spread_pips cannot be negative")
    if lower_timeframe <= timedelta(0) or higher_timeframe <= timedelta(0):
        raise ValueError("timeframe durations must be positive")

    results: list[BacktestTrade] = []
    index = 79
    while index < len(lower) - 1:
        signal_candle = lower[index]
        decision_time = signal_candle.time + lower_timeframe
        higher_available = [candle for candle in higher if candle.time + higher_timeframe <= decision_time]
        if len(higher_available) < 60:
            index += 1
            continue
        technical = assess_technicals(
            instrument,
            lower[max(0, index - 199) : index + 1],
            higher_available[-200:],
        )
        decision_spread = _spread_for(signal_candle, index, spread_pips, spread_model)
        half_spread = pip_size(instrument) * decision_spread / Decimal("2")
        quote = Quote(
            instrument=instrument,
            bid=signal_candle.close - half_spread,
            ask=signal_candle.close + half_spread,
            time=decision_time + timedelta(seconds=1),
        )
        fundamental = fundamentals.assess_pair(instrument, as_of=quote.time)
        candidate = fusion_policy.evaluate(technical, fundamental, quote)
        if candidate.disposition is DecisionDisposition.TRADE:
            future = lower[index + 1 : index + 1 + maximum_holding_bars + entry_delay_bars]
            if not future:
                break
            outcome = evaluate_candidate_outcome(
                candidate,
                future,
                maximum_bars=maximum_holding_bars + entry_delay_bars,
                spread_pips=spread_pips,
                spread_model=spread_model,
                entry_slippage_pips=entry_slippage_pips,
                exit_slippage_pips=exit_slippage_pips,
                entry_delay_bars=entry_delay_bars,
            )
            results.append(outcome)
            index += max(1, outcome.bars_held)
        else:
            index += 1
    return results, summarize_trades(results)


def _spread_for(candle: Candle, index: int, fallback: Decimal, model: SpreadModel | None) -> Decimal:
    value = fallback if model is None else model(candle, index)
    value = Decimal(str(value))
    if value < 0:
        raise ValueError("spread model cannot return a negative spread")
    return value


def _late_entry(candidate: TradeCandidate, entry_fill: Decimal, bars: int) -> BacktestTrade:
    return BacktestTrade(
        candidate.instrument,
        candidate.direction,
        candidate.signal_time,
        candidate.score,
        OutcomeStatus.TIMEOUT,
        Decimal("0"),
        bars,
        exit_reason="late_entry_invalid_geometry",
        entry_fill=entry_fill,
        exit_fill=entry_fill,
    )
