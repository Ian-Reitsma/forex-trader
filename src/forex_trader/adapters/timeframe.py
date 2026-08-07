from __future__ import annotations

from forex_trader.application.ports import MarketDataProvider
from forex_trader.domain.models import Candle, Quote
from forex_trader.domain.timeframes import validate_timeframe_pair


class TimeframeMappedMarketData:
    """Translate the engine's semantic lower/higher requests into configured research policy.

    The engine historically requested M5/H1 directly. This adapter preserves the stable
    application port while making those requests semantic aliases for the configured lower
    and higher strategy timeframes. Broker execution remains on the underlying provider.
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

    def candles(self, instrument: str, granularity: str, count: int) -> list[Candle]:
        requested = granularity.upper()
        mapped = (
            self.lower_timeframe
            if requested == "M5"
            else self.higher_timeframe
            if requested == "H1"
            else requested
        )
        return self.provider.candles(instrument, mapped, count)

    def quote(self, instrument: str) -> Quote:
        return self.provider.quote(instrument)
