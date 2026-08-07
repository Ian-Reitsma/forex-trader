from __future__ import annotations

from contextlib import contextmanager
from datetime import UTC, datetime

from forex_trader.adapters.synthetic import SyntheticMarketData
from forex_trader.adapters.timeframe import TimeframeMappedMarketData
from forex_trader.application.engine import TradingEngine
from forex_trader.application.fx_engine import FxTradingEngine


class CountingProvider:
    def __init__(self) -> None:
        self.inner = SyntheticMarketData(
            seed=19,
            direction="long",
            anchor=datetime(2026, 8, 6, 14, 0, tzinfo=UTC),
            quote_granularity="M5",
        )
        self.candle_calls: list[tuple[str, str, int]] = []
        self.quote_calls: list[str] = []

    def candles(self, instrument: str, granularity: str, count: int):  # type: ignore[no-untyped-def]
        self.candle_calls.append((instrument, granularity, count))
        return self.inner.candles(instrument, granularity, count)

    def quote(self, instrument: str):  # type: ignore[no-untyped-def]
        self.quote_calls.append(instrument)
        return self.inner.quote(instrument)


def test_snapshot_reuses_larger_completed_candle_request_for_smaller_request() -> None:
    provider = CountingProvider()
    market = TimeframeMappedMarketData(provider, lower_timeframe="M5", higher_timeframe="H1")
    with market.evaluation_scope():
        larger = market.candles("EUR_USD", "H1", 200)
        smaller = market.candles("EUR_USD", "H1", 81)
    assert provider.candle_calls == [("EUR_USD", "H1", 200)]
    assert smaller == larger[-81:]


def test_snapshot_refetches_when_later_request_needs_more_history() -> None:
    provider = CountingProvider()
    market = TimeframeMappedMarketData(provider)
    with market.evaluation_scope():
        market.candles("EUR_USD", "H1", 81)
        market.candles("EUR_USD", "H1", 200)
    assert provider.candle_calls == [
        ("EUR_USD", "H1", 81),
        ("EUR_USD", "H1", 200),
    ]


def test_snapshot_is_destroyed_between_top_level_evaluations() -> None:
    provider = CountingProvider()
    market = TimeframeMappedMarketData(provider)
    with market.evaluation_scope():
        market.candles("EUR_USD", "H1", 200)
    with market.evaluation_scope():
        market.candles("EUR_USD", "H1", 200)
    assert provider.candle_calls == [
        ("EUR_USD", "H1", 200),
        ("EUR_USD", "H1", 200),
    ]


def test_nested_scope_shares_snapshot_without_extending_lifetime() -> None:
    provider = CountingProvider()
    market = TimeframeMappedMarketData(provider)
    with market.evaluation_scope():
        market.candles("EUR_USD", "H1", 200)
        with market.evaluation_scope():
            market.candles("EUR_USD", "H1", 81)
    market.candles("EUR_USD", "H1", 81)
    assert provider.candle_calls == [
        ("EUR_USD", "H1", 200),
        ("EUR_USD", "H1", 81),
    ]


def test_quotes_are_never_cached_inside_snapshot_scope() -> None:
    provider = CountingProvider()
    market = TimeframeMappedMarketData(provider)
    with market.evaluation_scope():
        first = market.quote("EUR_USD")
        second = market.quote("EUR_USD")
    assert first == second
    assert provider.quote_calls == ["EUR_USD", "EUR_USD"]


def test_lower_history_minimum_is_cached_at_effective_count() -> None:
    provider = CountingProvider()
    market = TimeframeMappedMarketData(provider, lower_timeframe="M5", higher_timeframe="H1")
    with market.evaluation_scope():
        large = market.candles("EUR_USD", "M5", 200)
        again = market.candles("EUR_USD", "M5", 100)
    assert len(large) == market.minimum_lower_count
    assert again == large
    assert provider.candle_calls == [("EUR_USD", "M5", market.minimum_lower_count)]


def test_fx_engine_wraps_base_evaluation_in_market_snapshot(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    class ScopedMarket:
        active = False
        entries = 0

        @contextmanager
        def evaluation_scope(self):
            self.entries += 1
            self.active = True
            try:
                yield
            finally:
                self.active = False

    market = ScopedMarket()
    engine = object.__new__(FxTradingEngine)
    engine.market_data = market  # type: ignore[assignment]
    sentinel = object()

    def fake_base_evaluate(self, instrument: str, *, execute: bool = False):  # type: ignore[no-untyped-def]
        assert self.market_data.active is True
        assert instrument == "EUR_USD"
        assert execute is True
        return sentinel

    monkeypatch.setattr(TradingEngine, "evaluate", fake_base_evaluate)
    assert engine.evaluate("EUR_USD", execute=True) is sentinel
    assert market.entries == 1
    assert market.active is False


def test_fx_engine_falls_back_when_market_adapter_has_no_scope(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    engine = object.__new__(FxTradingEngine)
    engine.market_data = object()  # type: ignore[assignment]
    sentinel = object()
    monkeypatch.setattr(TradingEngine, "evaluate", lambda self, instrument, *, execute=False: sentinel)
    assert engine.evaluate("EUR_USD") is sentinel
