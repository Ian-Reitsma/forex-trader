from __future__ import annotations

from typing import Protocol

from forex_trader.domain.models import (
    AccountSnapshot,
    Candle,
    DecisionTrace,
    OrderRequest,
    OrderResult,
    Quote,
)


class MarketDataProvider(Protocol):
    def candles(self, instrument: str, granularity: str, count: int) -> list[Candle]: ...

    def quote(self, instrument: str) -> Quote: ...


class PaperBroker(Protocol):
    def account(self) -> AccountSnapshot: ...

    def place_market_order(self, request: OrderRequest) -> OrderResult: ...


class DecisionRepository(Protocol):
    def save_trace(self, trace: DecisionTrace) -> None: ...

    def recent_traces(self, limit: int = 20) -> list[dict[str, object]]: ...
