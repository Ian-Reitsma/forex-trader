from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from forex_trader.application.engine import TradingEngine
from forex_trader.domain.risk_day import fx_risk_day_key


class FxTradingEngine(TradingEngine):
    """Deployable FX engine with a 5 p.m. New York persistent risk-day boundary."""

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
