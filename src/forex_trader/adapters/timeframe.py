from __future__ import annotations

from forex_trader.application.ports import MarketDataProvider
from forex_trader.domain.models import Candle, Quote
from forex_trader.domain.timeframes import minimum_lower_history_count, validate_timeframe_pair


class TimeframeMappedMarketData:
    """Translate semantic lower/higher requests into the configured research policy.

    The application layer historically requests M5/H1 as semantic lower/higher aliases.
    This adapter maps them to the configured research pair. For lower-timeframe requests,
    it also enforces enough completed history to reconstruct a full current FX day plus
    the full prior day; otherwise finalized Asia/prior-day liquidity could be computed
    from a truncated M5 window.
    """

    def __init__(
        self,
        provider: MarketDataProvider,
        *,
        lower_timeframe: str = "M5",
        higher_timeframe: str = "H1",
    ) -> None:
        lower, higher = validate_timeframe_pair(lower_timeframe, higher_timeframe)
        self.provider = provider
        self.lower_timeframe = lower
        self.higher_timeframe = higher
        self.minimum_lower_count = minimum_lower_history_count(lower)

    def candles(self, instrument: str, granularity: str, count: int) -> list[Candle]:
        requested = granularity.upper()
        if requested == "M5":
            return self.provider.candles(
                instrument,
                self.lower_timeframe,
                max(count, self.minimum_lower_count),
            )
        if requested == "H1":
            return self.provider.candles(instrument, self.higher_timeframe, count)
        return self.provider.candles(instrument, requested, count)

    def quote(self, instrument: str) -> Quote:
        return self.provider.quote(instrument)
