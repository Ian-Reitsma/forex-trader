from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal


@dataclass(frozen=True, slots=True)
class PromotionMetrics:
    decisions: int
    trade_candidates: int
    submitted_orders: int
    rejected_orders: int
    unknown_orders: int
    closed_trades: int
    wins: int
    total_pl: Decimal
    gross_profit: Decimal
    gross_loss: Decimal
    max_drawdown: Decimal
    median_slippage_pips: Decimal | None = None
    active_days: int = 0
    instruments_traded: int = 0
    sessions_traded: int = 0
    unresolved_halts: int = 0

    @property
    def win_rate(self) -> Decimal:
        return Decimal("0") if self.closed_trades == 0 else Decimal(self.wins) / Decimal(self.closed_trades)

    @property
    def profit_factor(self) -> Decimal | None:
        return None if self.gross_loss == 0 else self.gross_profit / self.gross_loss

    @property
    def reject_rate(self) -> Decimal:
        return Decimal("0") if self.submitted_orders == 0 else Decimal(self.rejected_orders) / Decimal(self.submitted_orders)

    @property
    def unknown_rate(self) -> Decimal:
        return Decimal("0") if self.submitted_orders == 0 else Decimal(self.unknown_orders) / Decimal(self.submitted_orders)


@dataclass(frozen=True, slots=True)
class PromotionDecision:
    ready: bool
    reasons: tuple[str, ...]
    metrics: PromotionMetrics


class PracticePromotionPolicy:
    """Evidence gate for a long-running broker-Practice campaign, not a profit promise."""

    def __init__(
        self,
        *,
        minimum_decisions: int = 2_000,
        minimum_trade_candidates: int = 750,
        minimum_closed_trades: int = 500,
        minimum_active_days: int = 56,
        minimum_instruments_traded: int = 3,
        minimum_sessions_traded: int = 3,
        minimum_win_rate: Decimal = Decimal("0.43"),
        minimum_profit_factor: Decimal = Decimal("1.15"),
        maximum_reject_rate: Decimal = Decimal("0.02"),
        maximum_unknown_rate: Decimal = Decimal("0.005"),
        maximum_drawdown_fraction_of_profit: Decimal = Decimal("2.0"),
        maximum_median_slippage_pips: Decimal = Decimal("0.5"),
    ) -> None:
        self.minimum_decisions = minimum_decisions
        self.minimum_trade_candidates = minimum_trade_candidates
        self.minimum_closed_trades = minimum_closed_trades
        self.minimum_active_days = minimum_active_days
        self.minimum_instruments_traded = minimum_instruments_traded
        self.minimum_sessions_traded = minimum_sessions_traded
        self.minimum_win_rate = minimum_win_rate
        self.minimum_profit_factor = minimum_profit_factor
        self.maximum_reject_rate = maximum_reject_rate
        self.maximum_unknown_rate = maximum_unknown_rate
        self.maximum_drawdown_fraction_of_profit = maximum_drawdown_fraction_of_profit
        self.maximum_median_slippage_pips = maximum_median_slippage_pips

    def evaluate(self, metrics: PromotionMetrics) -> PromotionDecision:
        reasons: list[str] = []
        if metrics.decisions < self.minimum_decisions:
            reasons.append(f"decisions {metrics.decisions} < {self.minimum_decisions}")
        if metrics.trade_candidates < self.minimum_trade_candidates:
            reasons.append(f"trade candidates {metrics.trade_candidates} < {self.minimum_trade_candidates}")
        if metrics.closed_trades < self.minimum_closed_trades:
            reasons.append(f"closed trades {metrics.closed_trades} < {self.minimum_closed_trades}")
        if metrics.active_days < self.minimum_active_days:
            reasons.append(f"active days {metrics.active_days} < {self.minimum_active_days}")
        if metrics.instruments_traded < self.minimum_instruments_traded:
            reasons.append(f"instruments traded {metrics.instruments_traded} < {self.minimum_instruments_traded}")
        if metrics.sessions_traded < self.minimum_sessions_traded:
            reasons.append(f"sessions traded {metrics.sessions_traded} < {self.minimum_sessions_traded}")
        if metrics.unresolved_halts:
            reasons.append(f"{metrics.unresolved_halts} unresolved system halt(s)")
        if metrics.closed_trades and metrics.win_rate < self.minimum_win_rate:
            reasons.append(f"win rate {metrics.win_rate:.3f} < {self.minimum_win_rate}")
        pf = metrics.profit_factor
        if pf is None or pf < self.minimum_profit_factor:
            reasons.append("profit factor is unavailable" if pf is None else f"profit factor {pf:.3f} < {self.minimum_profit_factor}")
        if metrics.total_pl <= 0:
            reasons.append("net realized P/L is not positive")
        elif metrics.max_drawdown > metrics.total_pl * self.maximum_drawdown_fraction_of_profit:
            reasons.append("drawdown is too large relative to realized profit")
        if metrics.reject_rate > self.maximum_reject_rate:
            reasons.append(f"reject rate {metrics.reject_rate:.4f} exceeds limit")
        if metrics.unknown_rate > self.maximum_unknown_rate:
            reasons.append(f"unknown-order rate {metrics.unknown_rate:.4f} exceeds limit")
        if metrics.median_slippage_pips is not None and metrics.median_slippage_pips > self.maximum_median_slippage_pips:
            reasons.append("median slippage exceeds limit")
        return PromotionDecision(ready=not reasons, reasons=tuple(reasons), metrics=metrics)
