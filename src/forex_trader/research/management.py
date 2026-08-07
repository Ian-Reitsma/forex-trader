from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Iterable

from forex_trader.domain.enums import DecisionDisposition, Direction
from forex_trader.domain.models import Candle, TradeCandidate
from forex_trader.domain.technicals import pip_size
from forex_trader.research.backtest import OutcomeStatus


@dataclass(frozen=True, slots=True)
class ManagementPolicy:
    """Research-only trade-management policy.

    A policy may take one partial at a configured R multiple and optionally move the
    remaining stop to breakeven. The runner always targets the candidate's independently
    derived structural target. This object is intentionally not used by live execution.
    """

    name: str
    partial_at_r: Decimal | None = None
    partial_fraction: Decimal = Decimal("0")
    move_stop_to_break_even: bool = False

    def __post_init__(self) -> None:
        if not self.name.strip():
            raise ValueError("management policy name is required")
        if not Decimal("0") <= self.partial_fraction < Decimal("1"):
            raise ValueError("partial_fraction must be in [0, 1)")
        if self.partial_fraction > 0:
            if self.partial_at_r is None or self.partial_at_r <= 0:
                raise ValueError("positive partial_fraction requires positive partial_at_r")
        elif self.partial_at_r is not None:
            raise ValueError("partial_at_r requires a positive partial_fraction")
        if self.move_stop_to_break_even and self.partial_fraction <= 0:
            raise ValueError("breakeven move requires a partial exit")


STRUCTURAL_SINGLE_TARGET = ManagementPolicy("structural-single-target")
HALF_AT_ONE_R_RUNNER = ManagementPolicy(
    "half-at-1r-then-structural-runner",
    partial_at_r=Decimal("1"),
    partial_fraction=Decimal("0.5"),
    move_stop_to_break_even=True,
)


@dataclass(frozen=True, slots=True)
class ManagedTrade:
    instrument: str
    direction: Direction
    signal_time: object
    policy_name: str
    status: OutcomeStatus
    r_multiple: Decimal
    bars_held: int
    exit_reason: str
    partial_taken: bool = False
    partial_component_r: Decimal = Decimal("0")
    runner_component_r: Decimal = Decimal("0")
    ambiguous_bar: bool = False


@dataclass(frozen=True, slots=True)
class ManagementReport:
    policy_name: str
    trades: int
    positive_trades: int
    positive_fraction: Decimal
    total_r: Decimal
    average_r: Decimal
    max_drawdown_r: Decimal
    partial_frequency: Decimal
    ambiguous_fraction: Decimal


@dataclass(frozen=True, slots=True)
class ManagementScenario:
    candidate: TradeCandidate
    future_candles: tuple[Candle, ...]


def evaluate_management_outcome(
    candidate: TradeCandidate,
    future_candles: list[Candle] | tuple[Candle, ...],
    policy: ManagementPolicy,
    *,
    maximum_bars: int = 24,
    spread_pips: Decimal = Decimal("0"),
    exit_slippage_pips: Decimal = Decimal("0"),
) -> ManagedTrade:
    """Conservatively replay partial/runner management using completed OHLC candles.

    Exact intrabar ordering is unknowable from candles. Before a partial is established,
    if the stop and partial/target are both touched in one bar, the stop is assumed first.
    After a partial, if the runner stop and structural target are both touched in one bar,
    the runner stop is assumed first. Gap-through stops fill at the worse executable open.
    """
    if candidate.disposition is not DecisionDisposition.TRADE:
        raise ValueError("candidate must be tradeable")
    if candidate.entry_price is None or candidate.stop_loss is None or candidate.take_profit is None:
        raise ValueError("candidate must have entry, stop and structural target")
    if candidate.direction not in {Direction.LONG, Direction.SHORT}:
        raise ValueError("flat candidate cannot be managed")
    if maximum_bars < 1:
        raise ValueError("maximum_bars must be positive")
    if spread_pips < 0 or exit_slippage_pips < 0:
        raise ValueError("management execution costs cannot be negative")
    candles = [candle for candle in future_candles if candle.complete][:maximum_bars]
    if not candles:
        raise ValueError("at least one completed future candle is required")

    entry = candidate.entry_price
    original_stop = candidate.stop_loss
    target = candidate.take_profit
    risk = abs(entry - original_stop)
    if risk <= 0:
        raise ValueError("candidate stop distance must be positive")
    target_r = abs(target - entry) / risk
    pip = pip_size(candidate.instrument)
    half_spread = pip * spread_pips / Decimal("2")
    adverse_exit = pip * exit_slippage_pips
    partial_fraction = policy.partial_fraction
    runner_fraction = Decimal("1") - partial_fraction
    partial_level: Decimal | None = None
    if partial_fraction > 0:
        assert policy.partial_at_r is not None
        partial_level = (
            entry + risk * policy.partial_at_r
            if candidate.direction is Direction.LONG
            else entry - risk * policy.partial_at_r
        )
        # A partial beyond the independently derived target is nonsensical and would
        # silently turn the research policy into a different target policy.
        if policy.partial_at_r >= target_r:
            raise ValueError("partial_at_r must be below the structural target R")

    partial_taken = False
    partial_component = Decimal("0")
    runner_stop = original_stop
    ambiguous = False

    for index, candle in enumerate(candles, start=1):
        if candidate.direction is Direction.LONG:
            executable_open = candle.open - half_spread
            executable_low = candle.low - half_spread
            executable_high = candle.high - half_spread
            stop_hit = executable_low <= runner_stop
            target_hit = executable_high >= target
            partial_hit = (
                not partial_taken
                and partial_level is not None
                and executable_high >= partial_level
            )
        else:
            executable_open = candle.open + half_spread
            executable_low = candle.low + half_spread
            executable_high = candle.high + half_spread
            stop_hit = executable_high >= runner_stop
            target_hit = executable_low <= target
            partial_hit = (
                not partial_taken
                and partial_level is not None
                and executable_low <= partial_level
            )

        # Before the partial exists, OHLC cannot tell us whether price reached the
        # favorable threshold or the stop first. Assume the stop first and flag it.
        if not partial_taken and stop_hit:
            ambiguous = ambiguous or partial_hit or target_hit
            exit_fill = _adverse_stop_fill(
                candidate.direction,
                stop=original_stop,
                executable_open=executable_open,
                adverse_exit=adverse_exit,
            )
            full_r = _directional_r(candidate.direction, entry, exit_fill, risk)
            return ManagedTrade(
                candidate.instrument,
                candidate.direction,
                candidate.signal_time,
                policy.name,
                OutcomeStatus.LOSS,
                full_r,
                index,
                "gap_stop" if exit_fill != _slipped_level(candidate.direction, original_stop, adverse_exit) else "stop",
                ambiguous_bar=ambiguous,
            )

        if not partial_taken and target_hit:
            # Reaching the structural target necessarily crosses a lower favorable
            # partial threshold. Both fills can therefore be realized when no stop is
            # touched in the same candle.
            if partial_hit:
                assert policy.partial_at_r is not None
                partial_component = partial_fraction * _favorable_level_r(
                    candidate.direction,
                    entry,
                    partial_level,
                    risk,
                    adverse_exit,
                )
                runner_component = runner_fraction * _favorable_level_r(
                    candidate.direction,
                    entry,
                    target,
                    risk,
                    adverse_exit,
                )
                return ManagedTrade(
                    candidate.instrument,
                    candidate.direction,
                    candidate.signal_time,
                    policy.name,
                    OutcomeStatus.WIN,
                    partial_component + runner_component,
                    index,
                    "partial_then_structural_target",
                    partial_taken=True,
                    partial_component_r=partial_component,
                    runner_component_r=runner_component,
                )
            realized = _favorable_level_r(
                candidate.direction,
                entry,
                target,
                risk,
                adverse_exit,
            )
            return ManagedTrade(
                candidate.instrument,
                candidate.direction,
                candidate.signal_time,
                policy.name,
                OutcomeStatus.WIN,
                realized,
                index,
                "structural_target",
                runner_component_r=realized,
            )

        if partial_hit:
            assert partial_level is not None
            partial_taken = True
            partial_component = partial_fraction * _favorable_level_r(
                candidate.direction,
                entry,
                partial_level,
                risk,
                adverse_exit,
            )
            if policy.move_stop_to_break_even:
                runner_stop = entry
            continue

        if partial_taken and stop_hit:
            ambiguous = ambiguous or target_hit
            exit_fill = _adverse_stop_fill(
                candidate.direction,
                stop=runner_stop,
                executable_open=executable_open,
                adverse_exit=adverse_exit,
            )
            runner_r = runner_fraction * _directional_r(
                candidate.direction,
                entry,
                exit_fill,
                risk,
            )
            total = partial_component + runner_r
            return ManagedTrade(
                candidate.instrument,
                candidate.direction,
                candidate.signal_time,
                policy.name,
                _status_for_r(total),
                total,
                index,
                "runner_gap_stop" if exit_fill != _slipped_level(candidate.direction, runner_stop, adverse_exit) else "runner_stop",
                partial_taken=True,
                partial_component_r=partial_component,
                runner_component_r=runner_r,
                ambiguous_bar=ambiguous,
            )

        if partial_taken and target_hit:
            runner_r = runner_fraction * _favorable_level_r(
                candidate.direction,
                entry,
                target,
                risk,
                adverse_exit,
            )
            total = partial_component + runner_r
            return ManagedTrade(
                candidate.instrument,
                candidate.direction,
                candidate.signal_time,
                policy.name,
                OutcomeStatus.WIN,
                total,
                index,
                "runner_structural_target",
                partial_taken=True,
                partial_component_r=partial_component,
                runner_component_r=runner_r,
            )

    final = candles[-1]
    final_executable = (
        final.close - half_spread - adverse_exit
        if candidate.direction is Direction.LONG
        else final.close + half_spread + adverse_exit
    )
    runner_mark_r = _directional_r(candidate.direction, entry, final_executable, risk)
    lower_bound = Decimal("0") if partial_taken and policy.move_stop_to_break_even else Decimal("-1")
    runner_mark_r = max(lower_bound, min(target_r, runner_mark_r))
    if partial_taken:
        runner_component = runner_fraction * runner_mark_r
        total = partial_component + runner_component
    else:
        runner_component = runner_mark_r
        total = runner_component
    return ManagedTrade(
        candidate.instrument,
        candidate.direction,
        candidate.signal_time,
        policy.name,
        OutcomeStatus.TIMEOUT,
        total,
        len(candles),
        "timeout_mark",
        partial_taken=partial_taken,
        partial_component_r=partial_component,
        runner_component_r=runner_component,
        ambiguous_bar=ambiguous,
    )


def compare_management_policies(
    scenarios: Iterable[ManagementScenario],
    policies: Iterable[ManagementPolicy],
    *,
    maximum_bars: int = 24,
    spread_pips: Decimal = Decimal("0"),
    exit_slippage_pips: Decimal = Decimal("0"),
) -> tuple[ManagementReport, ...]:
    scenarios = tuple(scenarios)
    policies = tuple(policies)
    if not scenarios:
        raise ValueError("at least one management scenario is required")
    if not policies:
        raise ValueError("at least one management policy is required")
    reports: list[ManagementReport] = []
    for policy in policies:
        trades = [
            evaluate_management_outcome(
                scenario.candidate,
                scenario.future_candles,
                policy,
                maximum_bars=maximum_bars,
                spread_pips=spread_pips,
                exit_slippage_pips=exit_slippage_pips,
            )
            for scenario in scenarios
        ]
        reports.append(summarize_management(trades, policy_name=policy.name))
    return tuple(reports)


def summarize_management(
    trades: Iterable[ManagedTrade],
    *,
    policy_name: str,
) -> ManagementReport:
    selected = list(trades)
    if not selected:
        raise ValueError("at least one managed trade is required")
    total = sum((trade.r_multiple for trade in selected), Decimal("0"))
    positive = sum(trade.r_multiple > 0 for trade in selected)
    partials = sum(trade.partial_taken for trade in selected)
    ambiguous = sum(trade.ambiguous_bar for trade in selected)
    equity = Decimal("0")
    peak = Decimal("0")
    drawdown = Decimal("0")
    for trade in selected:
        equity += trade.r_multiple
        peak = max(peak, equity)
        drawdown = max(drawdown, peak - equity)
    count = Decimal(len(selected))
    return ManagementReport(
        policy_name=policy_name,
        trades=len(selected),
        positive_trades=positive,
        positive_fraction=Decimal(positive) / count,
        total_r=total,
        average_r=total / count,
        max_drawdown_r=drawdown,
        partial_frequency=Decimal(partials) / count,
        ambiguous_fraction=Decimal(ambiguous) / count,
    )


def _directional_r(direction: Direction, entry: Decimal, exit_price: Decimal, risk: Decimal) -> Decimal:
    return (
        (exit_price - entry) / risk
        if direction is Direction.LONG
        else (entry - exit_price) / risk
    )


def _slipped_level(direction: Direction, level: Decimal, adverse_exit: Decimal) -> Decimal:
    return level - adverse_exit if direction is Direction.LONG else level + adverse_exit


def _adverse_stop_fill(
    direction: Direction,
    *,
    stop: Decimal,
    executable_open: Decimal,
    adverse_exit: Decimal,
) -> Decimal:
    if direction is Direction.LONG:
        return min(stop, executable_open) - adverse_exit
    return max(stop, executable_open) + adverse_exit


def _favorable_level_r(
    direction: Direction,
    entry: Decimal,
    level: Decimal | None,
    risk: Decimal,
    adverse_exit: Decimal,
) -> Decimal:
    assert level is not None
    return _directional_r(
        direction,
        entry,
        _slipped_level(direction, level, adverse_exit),
        risk,
    )


def _status_for_r(value: Decimal) -> OutcomeStatus:
    if value > 0:
        return OutcomeStatus.WIN
    if value < 0:
        return OutcomeStatus.LOSS
    return OutcomeStatus.TIMEOUT
