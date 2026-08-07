from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from random import Random

from forex_trader.domain.models import Candle, Quote
from forex_trader.domain.technicals import pip_size


class SyntheticMarketData:
    """Deterministic provider for local development and tests."""

    def __init__(self, *, seed: int = 7, direction: str = "long") -> None:
        self.seed = seed
        self.direction = direction
        self._cache: dict[tuple[str, str, int], list[Candle]] = {}

    def candles(self, instrument: str, granularity: str, count: int) -> list[Candle]:
        key = (instrument, granularity, count)
        if key not in self._cache:
            self._cache[key] = self._generate(instrument, granularity, count)
        return list(self._cache[key])

    def quote(self, instrument: str) -> Quote:
        candles = self.candles(instrument, "M5", 200)
        mid = candles[-1].close
        half = pip_size(instrument) * Decimal("0.45")
        return Quote(instrument, mid - half, mid + half, candles[-1].time + timedelta(seconds=1))

    def _generate(self, instrument: str, granularity: str, count: int) -> list[Candle]:
        random = Random(f"{self.seed}:{instrument}:{granularity}:{self.direction}")
        step = timedelta(minutes=5 if granularity == "M5" else 60)
        now = datetime(2026, 1, 5, tzinfo=UTC)
        base = Decimal("1.1000") if not instrument.endswith("_JPY") else Decimal("150.00")
        pip = pip_size(instrument)
        trend_sign = Decimal("1") if self.direction == "long" else Decimal("-1")
        candles: list[Candle] = []
        price = base
        for index in range(count):
            drift = trend_sign * pip * (Decimal("0.22") if granularity == "H1" else Decimal("0.08"))
            noise = Decimal(str(random.uniform(-0.18, 0.18))) * pip
            open_price = price
            close = price + drift + noise
            high = max(open_price, close) + pip * Decimal(str(random.uniform(0.25, 0.75)))
            low = min(open_price, close) - pip * Decimal(str(random.uniform(0.25, 0.75)))
            candles.append(Candle(now + step * index, open_price, high, low, close, 100 + index))
            price = close

        if granularity == "M5" and count >= 20:
            previous = candles[-2]
            lookback = candles[-11:-1]
            if self.direction == "long":
                swept = min(c.low for c in lookback) - pip * Decimal("1.2")
                open_price = previous.close - pip * Decimal("0.3")
                close = previous.close + pip * Decimal("2.8")
                candles[-1] = Candle(candles[-1].time, open_price, close + pip, swept, close, 500)
            else:
                swept = max(c.high for c in lookback) + pip * Decimal("1.2")
                open_price = previous.close + pip * Decimal("0.3")
                close = previous.close - pip * Decimal("2.8")
                candles[-1] = Candle(candles[-1].time, open_price, swept, close - pip, close, 500)
        return candles
