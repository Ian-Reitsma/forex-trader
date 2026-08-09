from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Sequence

from forex_trader.domain.enums import DecisionDisposition, Direction
from forex_trader.domain.models import TradeCandidate
from forex_trader.domain.technicals import pip_size
from forex_trader.research.backtest import BacktestTrade, OutcomeStatus
from forex_trader.research.partial_runner_backtest import PartialRunnerProfile
from forex_trader.research.public_history import HistoricalTick


@dataclass(frozen=True, slots=True)
class ExactPartialRunnerOutcome:
    trade: BacktestTrade
    entry_time: datetime
    exit_time: datetime
    first_target_time: datetime | None

    def __post_init__(self) -> None:
        if self.entry_time.tzinfo is None or self.exit_time.tzinfo is None:
            raise ValueError("partial-runner timestamps must be timezone-aware")
        if self.exit_time < self.entry_time:
            raise ValueError("exit_time cannot precede entry_time")
        if self.first_target_time is not None:
            if self.first_target_time.tzinfo is None:
                raise ValueError("first_target_time must be timezone-aware")
            if not self.entry_time <= self.first_target_time <= self.exit_time:
                raise ValueError("first_target_time must lie within the trade lifetime")


def _economic_status(realized_r: Decimal) -> OutcomeStatus:
    if realized_r > 0:
        return OutcomeStatus.WIN
    if realized_r < 0:
        return OutcomeStatus.LOSS
    return OutcomeStatus.TIMEOUT


def evaluate_exact_partial_runner(
    candidate: TradeCandidate,
    ticks: Sequence[HistoricalTick],
    *,
    entry_index: int,
    profile: PartialRunnerProfile,
    maximum_holding: timedelta = timedelta(hours=2),
    adverse_slippage_pips: Decimal = Decimal("0.10"),
) -> ExactPartialRunnerOutcome:
    """Replay one partial-profit + break-even-runner profile on exact executable ticks.

    The original structural stop remains active until the first target executes. After
    that fill, the remaining fraction is protected at the original entry fill and can
    continue toward the runner target. Trigger ordering is the exact bid/ask tick order;
    entry, partial and final fills all include the configured adverse slippage.
    """
    if candidate.disposition is not DecisionDisposition.TRADE:
        raise ValueError("candidate must be tradeable")
    if candidate.entry_price is None or candidate.stop_loss is None or candidate.take_profit is None:
        raise ValueError("candidate must have entry, stop, and target")
    if not 0 <= entry_index < len(ticks):
        raise ValueError("entry_index is outside tick history")
    if maximum_holding <= timedelta(0):
        raise ValueError("maximum_holding must be positive")
    if adverse_slippage_pips < 0:
        raise ValueError("adverse_slippage_pips cannot be negative")

    entry_tick = ticks[entry_index]
    if entry_tick.instrument.upper() != candidate.instrument.upper():
        raise ValueError("candidate and tick instruments do not match")
    pip = pip_size(candidate.instrument)
    slippage = pip * adverse_slippage_pips
    if candidate.direction is Direction.LONG:
        entry_fill = entry_tick.ask + slippage
        if entry_fill <= candidate.stop_loss:
            raise ValueError("long entry must remain above structural stop")
    elif candidate.direction is Direction.SHORT:
        entry_fill = entry_tick.bid - slippage
        if entry_fill >= candidate.stop_loss:
            raise ValueError("short entry must remain below structural stop")
    else:
        raise ValueError("flat candidate cannot be backtested")

    risk = abs(entry_fill - candidate.stop_loss)
    if risk <= 0:
        raise ValueError("candidate stop distance must be positive")
    remaining_fraction = Decimal("1") - profile.first_exit_fraction
    first_target_price = (
        entry_fill + risk * profile.first_target_r
        if candidate.direction is Direction.LONG
        else entry_fill - risk * profile.first_target_r
    )
    runner_target_price = (
        entry_fill + risk * profile.runner_target_r
        if candidate.direction is Direction.LONG
        else entry_fill - risk * profile.runner_target_r
    )
    deadline = entry_tick.time + maximum_holding
    first_target_time: datetime | None = None
    first_realized_r = Decimal("0")
    max_favorable_r = Decimal("0")
    max_adverse_r = Decimal("0")
    last_tick = entry_tick

    def outcome(
        *,
        tick: HistoricalTick,
        realized_r: Decimal,
        exit_fill: Decimal,
        reason: str,
    ) -> ExactPartialRunnerOutcome:
        bars_held = max(1, math.ceil((tick.time - entry_tick.time).total_seconds() / 300))
        return ExactPartialRunnerOutcome(
            trade=BacktestTrade(
                candidate.instrument,
                candidate.direction,
                candidate.signal_time,
                candidate.score,
                _economic_status(realized_r),
                realized_r,
                bars_held,
                exit_reason=reason,
                entry_fill=entry_fill,
                exit_fill=exit_fill,
                maximum_favorable_r=max_favorable_r,
                maximum_adverse_r=max_adverse_r,
                estimated_cost_r=Decimal("2") * slippage / risk,
            ),
            entry_time=entry_tick.time,
            exit_time=tick.time,
            first_target_time=first_target_time,
        )

    for tick_index in range(entry_index, len(ticks)):
        tick = ticks[tick_index]
        if tick.time > deadline:
            break
        last_tick = tick
        if candidate.direction is Direction.LONG:
            executable_exit = tick.bid
            favorable = max(Decimal("0"), (executable_exit - entry_fill) / risk)
            adverse = max(Decimal("0"), (entry_fill - executable_exit) / risk)
            structural_stop_hit = executable_exit <= candidate.stop_loss
        else:
            executable_exit = tick.ask
            favorable = max(Decimal("0"), (entry_fill - executable_exit) / risk)
            adverse = max(Decimal("0"), (executable_exit - entry_fill) / risk)
            structural_stop_hit = executable_exit >= candidate.stop_loss
        max_favorable_r = max(max_favorable_r, favorable)
        max_adverse_r = max(max_adverse_r, adverse)

        if first_target_time is None:
            if structural_stop_hit:
                if candidate.direction is Direction.LONG:
                    exit_fill = min(executable_exit, candidate.stop_loss) - slippage
                    realized_r = (exit_fill - entry_fill) / risk
                else:
                    exit_fill = max(executable_exit, candidate.stop_loss) + slippage
                    realized_r = (entry_fill - exit_fill) / risk
                return outcome(
                    tick=tick,
                    realized_r=realized_r,
                    exit_fill=exit_fill,
                    reason=f"partial_runner_structural_stop|{profile.identity}",
                )

            first_hit = (
                executable_exit >= first_target_price
                if candidate.direction is Direction.LONG
                else executable_exit <= first_target_price
            )
            if not first_hit:
                continue
            first_target_time = tick.time
            if candidate.direction is Direction.LONG:
                first_fill = first_target_price - slippage
                first_leg_r = (first_fill - entry_fill) / risk
            else:
                first_fill = first_target_price + slippage
                first_leg_r = (entry_fill - first_fill) / risk
            first_realized_r = first_leg_r * profile.first_exit_fraction

        if candidate.direction is Direction.LONG:
            runner_hit = executable_exit >= runner_target_price
            breakeven_hit = executable_exit <= entry_fill
        else:
            runner_hit = executable_exit <= runner_target_price
            breakeven_hit = executable_exit >= entry_fill

        if runner_hit:
            if candidate.direction is Direction.LONG:
                exit_fill = runner_target_price - slippage
                runner_r = (exit_fill - entry_fill) / risk
            else:
                exit_fill = runner_target_price + slippage
                runner_r = (entry_fill - exit_fill) / risk
            return outcome(
                tick=tick,
                realized_r=first_realized_r + runner_r * remaining_fraction,
                exit_fill=exit_fill,
                reason=f"partial_runner_target|{profile.identity}",
            )

        if breakeven_hit:
            if candidate.direction is Direction.LONG:
                exit_fill = min(executable_exit, entry_fill) - slippage
                runner_r = (exit_fill - entry_fill) / risk
            else:
                exit_fill = max(executable_exit, entry_fill) + slippage
                runner_r = (entry_fill - exit_fill) / risk
            return outcome(
                tick=tick,
                realized_r=first_realized_r + runner_r * remaining_fraction,
                exit_fill=exit_fill,
                reason=f"partial_runner_breakeven|{profile.identity}",
            )

    if candidate.direction is Direction.LONG:
        exit_fill = last_tick.bid - slippage
        runner_or_full_r = (exit_fill - entry_fill) / risk
    else:
        exit_fill = last_tick.ask + slippage
        runner_or_full_r = (entry_fill - exit_fill) / risk
    realized_r = (
        first_realized_r + runner_or_full_r * remaining_fraction
        if first_target_time is not None
        else runner_or_full_r
    )
    return outcome(
        tick=last_tick,
        realized_r=realized_r,
        exit_fill=exit_fill,
        reason=f"partial_runner_time_stop|{profile.identity}",
    )
