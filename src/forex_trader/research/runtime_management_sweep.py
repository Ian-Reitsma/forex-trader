from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta
from decimal import Decimal
from itertools import product
from typing import Iterable, Sequence, TypeVar

from forex_trader.domain.models import Candle, TradeCandidate
from forex_trader.domain.position_management import RuntimeManagementPolicy
from forex_trader.research.backtest import BacktestTrade, summarize_trades
from forex_trader.research.runtime_management_shadow import evaluate_runtime_management_shadow


@dataclass(frozen=True, slots=True)
class RuntimeManagementSweepPoint:
    progress_check_minutes: int
    minimum_progress_r: Decimal
    maximum_holding_minutes: int
    break_even_after_r: Decimal

    def policy(self) -> RuntimeManagementPolicy:
        return RuntimeManagementPolicy(
            progress_check_after=timedelta(minutes=self.progress_check_minutes),
            minimum_progress_r=self.minimum_progress_r,
            maximum_holding_time=timedelta(minutes=self.maximum_holding_minutes),
            break_even_after_r=self.break_even_after_r,
        )

    def to_jsonable(self) -> dict[str, object]:
        return {
            "progress_check_minutes": self.progress_check_minutes,
            "minimum_progress_r": str(self.minimum_progress_r),
            "maximum_holding_minutes": self.maximum_holding_minutes,
            "break_even_after_r": str(self.break_even_after_r),
        }


def default_runtime_management_grid() -> tuple[RuntimeManagementSweepPoint, ...]:
    return tuple(
        RuntimeManagementSweepPoint(check, minimum, maximum, break_even)
        for check, minimum, maximum, break_even in product(
            (15, 20, 30, 45, 60),
            (Decimal("0"), Decimal("0.05"), Decimal("0.10"), Decimal("0.15"), Decimal("0.20"), Decimal("0.30")),
            (60, 90, 120, 180),
            (Decimal("0.50"), Decimal("0.75"), Decimal("1.00")),
        )
        if check < maximum
    )


def evaluate_sweep_point(
    point: RuntimeManagementSweepPoint,
    samples: Sequence[tuple[TradeCandidate, Sequence[Candle], Decimal]],
    *,
    exit_slippage_pips: Decimal = Decimal("0.10"),
) -> dict[str, object]:
    if exit_slippage_pips < 0:
        raise ValueError("exit_slippage_pips cannot be negative")
    trades: list[BacktestTrade] = []
    policy = point.policy()
    for candidate, candles, spread_pips in samples:
        trades.append(
            evaluate_runtime_management_shadow(
                candidate,
                candles,
                policy,
                spread_pips=spread_pips,
                exit_slippage_pips=exit_slippage_pips,
            )
        )
    summary = summarize_trades(trades)
    positive = sum(1 for trade in trades if trade.r_multiple > 0)
    return {
        "policy": point.to_jsonable(),
        "trades": summary.trades,
        "wins": summary.wins,
        "losses": summary.losses,
        "timeouts": summary.timeouts,
        "win_rate": str(summary.win_rate),
        "expectancy_r": str(summary.expectancy_r),
        "total_r": str(summary.total_r),
        "max_drawdown_r": str(summary.max_drawdown_r),
        "positive_trade_fraction": str(Decimal(positive) / Decimal(len(trades))) if trades else "0",
    }


T = TypeVar("T")


def chronological_holdout_split(
    items: Sequence[T],
    *,
    train_fraction: Decimal = Decimal("0.625"),
) -> tuple[tuple[T, ...], tuple[T, ...]]:
    if not Decimal("0") < train_fraction < Decimal("1"):
        raise ValueError("train_fraction must be in (0,1)")
    if len(items) < 4:
        raise ValueError("at least four samples are required for chronological holdout")
    split = int((Decimal(len(items)) * train_fraction).to_integral_value())
    split = max(2, min(len(items) - 2, split))
    return tuple(items[:split]), tuple(items[split:])


def rank_sweep_results(results: Iterable[dict[str, object]]) -> tuple[dict[str, object], ...]:
    def key(row: dict[str, object]) -> tuple[Decimal, Decimal, Decimal]:
        return (
            Decimal(str(row["expectancy_r"])),
            Decimal(str(row["total_r"])),
            -Decimal(str(row["max_drawdown_r"])),
        )

    return tuple(sorted(results, key=key, reverse=True))
