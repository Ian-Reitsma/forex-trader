from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from uuid import uuid4

from forex_trader.adapters.synthetic import SyntheticMarketData
from forex_trader.adapters.timeframe import TimeframeMappedMarketData
from forex_trader.domain.correlation_risk import CorrelationRiskGuard
from forex_trader.domain.enums import DecisionDisposition, Direction
from forex_trader.domain.models import TradeCandidate
from forex_trader.domain.portfolio import OpenPosition


class CountingProvider:
    def __init__(self) -> None:
        self.inner = SyntheticMarketData(
            seed=23,
            direction="long",
            anchor=datetime(2026, 8, 6, 14, 0, tzinfo=UTC),
            quote_granularity="M5",
        )
        self.calls: list[tuple[str, str, int]] = []

    def candles(self, instrument: str, granularity: str, count: int):  # type: ignore[no-untyped-def]
        self.calls.append((instrument, granularity, count))
        return self.inner.candles(instrument, granularity, count)

    def quote(self, instrument: str):  # type: ignore[no-untyped-def]
        return self.inner.quote(instrument)


def candidate() -> TradeCandidate:
    return TradeCandidate(
        candidate_id=uuid4(),
        instrument="EUR_USD",
        direction=Direction.LONG,
        disposition=DecisionDisposition.TRADE,
        score=Decimal("0.80"),
        entry_price=Decimal("1.1000"),
        stop_loss=Decimal("1.0980"),
        take_profit=Decimal("1.1040"),
        technical_score=Decimal("0.80"),
        fundamental_score=Decimal("0.50"),
        reasons=("test",),
    )


def test_higher_timeframe_technical_snapshot_is_reused_by_correlation_guard() -> None:
    provider = CountingProvider()
    market = TimeframeMappedMarketData(provider, lower_timeframe="M5", higher_timeframe="H1")
    guard = CorrelationRiskGuard(
        market.candles,
        semantic_granularity="H1",
        lookback=80,
        minimum_observations=40,
        maximum_signed_correlation=0.99,
        fail_closed=True,
    )
    positions = [OpenPosition("GBP_USD", Decimal("1000"), Decimal("0"))]

    with market.evaluation_scope():
        technical_context = market.candles("EUR_USD", "H1", 200)
        result = guard.evaluate(candidate(), positions)

    assert len(technical_context) == 200
    assert len(result.pairs) == 1
    assert result.pairs[0].observations >= 40
    # EUR_USD correlation needs 80 bars, but the already-fetched 200-bar technical
    # snapshot satisfies it. Only the genuinely new GBP_USD history is fetched.
    assert provider.calls == [
        ("EUR_USD", "H1", 200),
        ("GBP_USD", "H1", 80),
    ]
