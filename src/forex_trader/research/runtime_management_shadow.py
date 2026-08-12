from __future__ import annotations

from datetime import timedelta
from decimal import Decimal

from forex_trader.domain.enums import DecisionDisposition, Direction
from forex_trader.domain.models import Candle, TradeCandidate
from forex_trader.domain.position_management import ManagementAction, PositionManagementContext, RuntimeManagementPolicy
from forex_trader.domain.technicals import pip_size
from forex_trader.research.backtest import BacktestTrade, OutcomeStatus


def evaluate_runtime_management_shadow(
    candidate: TradeCandidate,
    future_candles: list[Candle] | tuple[Candle, ...],
    policy: RuntimeManagementPolicy | None = None,
    *,
    spread_pips: Decimal = Decimal("0"),
    exit_slippage_pips: Decimal = Decimal("0"),
) -> BacktestTrade:
    """Replay the runtime management policy without broker write authority.

    The policy is evaluated at each completed candle close. Stop/target touches inside a
    candle are processed before close-time management and same-bar stop+target ambiguity is
    resolved stop-first. No event time or synthetic structure invalidation is invented.
    """
    active_policy = policy or RuntimeManagementPolicy()
    if candidate.disposition is not DecisionDisposition.TRADE:
        raise ValueError("candidate must be tradeable")
    if candidate.entry_price is None or candidate.stop_loss is None or candidate.take_profit is None:
        raise ValueError("candidate must have entry, stop and target")
    if candidate.direction not in {Direction.LONG, Direction.SHORT}:
        raise ValueError("flat candidate cannot be managed")
    if spread_pips < 0 or exit_slippage_pips < 0:
        raise ValueError("execution costs cannot be negative")
    candles = [candle for candle in future_candles if candle.complete]
    if not candles:
        raise ValueError("at least one completed future candle is required")

    step = _bar_step(candles)
    entry = candidate.entry_price
    original_stop = candidate.stop_loss
    target = candidate.take_profit
    risk = abs(entry - original_stop)
    if risk <= 0:
        raise ValueError("candidate stop distance must be positive")
    pip = pip_size(candidate.instrument)
    half_spread = pip * spread_pips / Decimal("2")
    adverse_exit = pip * exit_slippage_pips
    active_stop = original_stop
    max_favorable = Decimal("0")
    max_adverse = Decimal("0")
    protection_moved = False

    for index, candle in enumerate(candles, start=1):
        if candidate.direction is Direction.LONG:
            executable_open = candle.open - half_spread
            executable_low = candle.low - half_spread
            executable_high = candle.high - half_spread
            executable_close = candle.close - half_spread
            max_favorable = max(max_favorable, max(Decimal("0"), (executable_high - entry) / risk))
            max_adverse = max(max_adverse, max(Decimal("0"), (entry - executable_low) / risk))
            stop_hit = executable_low <= active_stop
            target_hit = executable_high >= target
            if stop_hit:
                fill = min(active_stop, executable_open) - adverse_exit
                realized = (fill - entry) / risk
                return _trade(
                    candidate,
                    _status_for_realized(realized),
                    realized,
                    index,
                    "shadow_stop",
                    entry,
                    fill,
                    max_favorable,
                    max_adverse,
                    target_hit,
                    adverse_exit / risk,
                )
            if target_hit:
                fill = target - adverse_exit
                realized = (fill - entry) / risk
                return _trade(
                    candidate,
                    _status_for_realized(realized),
                    realized,
                    index,
                    "shadow_target",
                    entry,
                    fill,
                    max_favorable,
                    max_adverse,
                    False,
                    adverse_exit / risk,
                )
        else:
            executable_open = candle.open + half_spread
            executable_low = candle.low + half_spread
            executable_high = candle.high + half_spread
            executable_close = candle.close + half_spread
            max_favorable = max(max_favorable, max(Decimal("0"), (entry - executable_low) / risk))
            max_adverse = max(max_adverse, max(Decimal("0"), (executable_high - entry) / risk))
            stop_hit = executable_high >= active_stop
            target_hit = executable_low <= target
            if stop_hit:
                fill = max(active_stop, executable_open) + adverse_exit
                realized = (entry - fill) / risk
                return _trade(
                    candidate,
                    _status_for_realized(realized),
                    realized,
                    index,
                    "shadow_stop",
                    entry,
                    fill,
                    max_favorable,
                    max_adverse,
                    target_hit,
                    adverse_exit / risk,
                )
            if target_hit:
                fill = target + adverse_exit
                realized = (entry - fill) / risk
                return _trade(
                    candidate,
                    _status_for_realized(realized),
                    realized,
                    index,
                    "shadow_target",
                    entry,
                    fill,
                    max_favorable,
                    max_adverse,
                    False,
                    adverse_exit / risk,
                )

        observed_at = candle.time + step
        intent = active_policy.decide(
            PositionManagementContext(
                instrument=candidate.instrument,
                direction=candidate.direction,
                opened_at=candidate.signal_time,
                observed_at=max(candidate.signal_time, observed_at),
                entry_price=entry,
                current_price=executable_close,
                stop_loss=original_stop,
                take_profit=target,
            )
        )
        if intent.action is ManagementAction.MOVE_PROTECTION and not protection_moved:
            active_stop = intent.new_stop_loss or entry
            protection_moved = True
            continue
        if intent.action is ManagementAction.CLOSE:
            fill = executable_close - adverse_exit if candidate.direction is Direction.LONG else executable_close + adverse_exit
            realized = (fill - entry) / risk if candidate.direction is Direction.LONG else (entry - fill) / risk
            return _trade(
                candidate,
                _status_for_realized(realized),
                realized,
                index,
                f"shadow_management:{intent.reason}",
                entry,
                fill,
                max_favorable,
                max_adverse,
                False,
                adverse_exit / risk,
            )

    final = candles[-1]
    final_fill = (
        final.close - half_spread - adverse_exit
        if candidate.direction is Direction.LONG
        else final.close + half_spread + adverse_exit
    )
    realized = (final_fill - entry) / risk if candidate.direction is Direction.LONG else (entry - final_fill) / risk
    return _trade(
        candidate,
        OutcomeStatus.TIMEOUT,
        realized,
        len(candles),
        "shadow_observation_horizon_ended",
        entry,
        final_fill,
        max_favorable,
        max_adverse,
        False,
        adverse_exit / risk,
    )


def _status_for_realized(realized: Decimal) -> OutcomeStatus:
    if realized > 0:
        return OutcomeStatus.WIN
    if realized < 0:
        return OutcomeStatus.LOSS
    return OutcomeStatus.TIMEOUT


def _bar_step(candles: list[Candle]) -> timedelta:
    positive = [current.time - previous.time for previous, current in zip(candles, candles[1:]) if current.time > previous.time]
    return min(positive) if positive else timedelta(minutes=5)


def _trade(
    candidate: TradeCandidate,
    status: OutcomeStatus,
    r_multiple: Decimal,
    bars_held: int,
    exit_reason: str,
    entry_fill: Decimal,
    exit_fill: Decimal,
    maximum_favorable_r: Decimal,
    maximum_adverse_r: Decimal,
    ambiguous_bar: bool,
    estimated_cost_r: Decimal,
) -> BacktestTrade:
    return BacktestTrade(
        instrument=candidate.instrument,
        direction=candidate.direction,
        signal_time=candidate.signal_time,
        score=candidate.score,
        status=status,
        r_multiple=r_multiple,
        bars_held=bars_held,
        exit_reason=exit_reason,
        entry_fill=entry_fill,
        exit_fill=exit_fill,
        ambiguous_bar=ambiguous_bar,
        maximum_favorable_r=maximum_favorable_r,
        maximum_adverse_r=maximum_adverse_r,
        estimated_cost_r=estimated_cost_r,
    )
