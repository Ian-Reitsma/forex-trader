from __future__ import annotations

from decimal import Decimal
from typing import Protocol

from forex_trader.domain.models import (
    AccountSnapshot,
    Candle,
    DecisionTrace,
    OrderRequest,
    OrderResult,
    Quote,
)
from forex_trader.domain.portfolio import OpenPosition


class MarketDataProvider(Protocol):
    def candles(self, instrument: str, granularity: str, count: int) -> list[Candle]: ...

    def quote(self, instrument: str) -> Quote: ...


class PaperBroker(Protocol):
    def account(self) -> AccountSnapshot: ...

    def positions(self) -> list[OpenPosition]: ...

    def has_open_position(self, instrument: str) -> bool: ...

    def conversion_rate(self, from_currency: str, to_currency: str) -> Decimal | None: ...

    def place_market_order(self, request: OrderRequest) -> OrderResult: ...

    def reconcile_order(
        self,
        *,
        client_order_id: str,
        instrument: str,
        units: int,
    ) -> OrderResult | None: ...


class DecisionRepository(Protocol):
    def save_trace(self, trace: DecisionTrace) -> None: ...

    def recent_traces(self, limit: int = 20) -> list[dict[str, object]]: ...

    def claim_execution(self, execution_key: str) -> bool: ...

    def release_execution(self, execution_key: str) -> None: ...
