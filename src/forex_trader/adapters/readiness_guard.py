from __future__ import annotations

from typing import Any

from forex_trader.domain.models import OrderRequest, OrderResult


class ReconciliationGuardedBroker:
    """Delegate broker reads but fail closed on writes until reconciliation is durable."""

    def __init__(self, broker: object, repository: object) -> None:
        self._broker = broker
        self._repository = repository

    def __getattr__(self, name: str) -> Any:
        return getattr(self._broker, name)

    def place_market_order(self, request: OrderRequest) -> OrderResult:
        account = self._broker.account()
        checker = getattr(self._repository, "execution_ready", None)
        if checker is None or not bool(checker(account.account_id)):
            raise RuntimeError(
                "Practice broker write blocked: durable broker reconciliation readiness has not been established; run forex-trader sync"
            )
        return self._broker.place_market_order(request)
