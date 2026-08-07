from __future__ import annotations

from contextlib import nullcontext
from datetime import datetime
from decimal import Decimal

from forex_trader.application.engine import TradingEngine
from forex_trader.domain.models import DecisionTrace
from forex_trader.domain.risk_day import fx_risk_day_key


class FxTradingEngine(TradingEngine):
    """Deployable FX engine with FX risk-day and evaluation-snapshot semantics."""

    def evaluate(self, instrument: str, *, execute: bool = False) -> DecisionTrace:
        """Evaluate one instrument inside an optional completed-candle snapshot scope.

        The market-data adapter may reuse completed candles inside this one decision. Live
        quotes, account state and broker writes are deliberately outside that cache.
        """
        scope_factory = getattr(self.market_data, "evaluation_scope", None)
        scope = scope_factory() if callable(scope_factory) else nullcontext()
        with scope:
            return super().evaluate(instrument, execute=execute)

    def _observe_latched_loss(self, account, signal_time: datetime, capital_base: Decimal) -> bool:  # type: ignore[no-untyped-def]
        observe = getattr(self.repository, "observe_risk_day", None)
        if observe is None or capital_base <= 0:
            return False
        marked_pl = account.realized_pl_today + account.unrealized_pl
        return bool(
            observe(
                account_id=account.account_id,
                trading_day=fx_risk_day_key(signal_time),
                marked_pl=marked_pl,
                loss_limit_amount=capital_base * self.risk_policy.max_daily_loss_fraction,
            )
        )
