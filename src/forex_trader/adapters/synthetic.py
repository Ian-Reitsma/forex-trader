from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from random import Random

from forex_trader.domain.instruments import pip_size_for
from forex_trader.domain.models import Candle, Quote


class SyntheticMarketData:
    """Deterministic provider for local development and complete setup-path tests."""

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
        half = pip_size_for(instrument) * Decimal("0.45")
        return Quote(instrument, mid - half, mid + half, candles[-1].time + timedelta(seconds=1), bid_liquidity=Decimal("10000000"), ask_liquidity=Decimal("10000000"))

    def quote_for_units(self, instrument: str, units: int | None) -> Quote:
        return self.quote(instrument)

    def _generate(self, instrument: str, granularity: str, count: int) -> list[Candle]:
        random = Random(f"{self.seed}:{instrument}:{granularity}:{self.direction}")
        step = timedelta(minutes=5 if granularity == "M5" else 60)
        now = datetime(2026, 1, 5, tzinfo=UTC)
        base = Decimal("1.1000") if not instrument.endswith("_JPY") else Decimal("150.00")
        pip = pip_size_for(instrument)
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

        if granularity == "M5" and count >= 30:
            self._inject_setup(candles, pip)
        return candles

    def _inject_setup(self, candles: list[Candle], pip: Decimal) -> None:
        reference = candles[-15].close
        times = [candle.time for candle in candles[-14:]]
        vol = 500
        if self.direction == "long":
            values = [
                (reference, reference + pip * Decimal("0.2"), reference + pip * Decimal("0.5"), reference - pip * Decimal("0.5")),
                (reference + pip * Decimal("0.2"), reference + pip * Decimal("2.5"), reference + pip * Decimal("2.9"), reference),
                (reference + pip * Decimal("2.5"), reference + pip * Decimal("4.0"), reference + pip * Decimal("4.4"), reference + pip * Decimal("2.2")),
                (reference + pip * Decimal("4.0"), reference + pip * Decimal("4.4"), reference + pip * Decimal("5.0"), reference + pip * Decimal("3.5")),
                (reference + pip * Decimal("4.4"), reference + pip * Decimal("3.2"), reference + pip * Decimal("4.7"), reference + pip * Decimal("2.1")),
                (reference + pip * Decimal("3.2"), reference + pip * Decimal("4.2"), reference + pip * Decimal("4.8"), reference + pip * Decimal("2.8")),
                (reference + pip * Decimal("4.2"), reference + pip * Decimal("3.0"), reference + pip * Decimal("4.4"), reference + pip * Decimal("1.6")),
                (reference + pip * Decimal("3.0"), reference + pip * Decimal("4.0"), reference + pip * Decimal("4.6"), reference + pip * Decimal("2.7")),
                (reference + pip * Decimal("4.0"), reference + pip * Decimal("3.3"), reference + pip * Decimal("4.3"), reference + pip * Decimal("2.4")),
                (reference + pip * Decimal("3.3"), reference + pip * Decimal("4.1"), reference + pip * Decimal("4.9"), reference + pip * Decimal("2.9")),
                (reference + pip * Decimal("4.1"), reference + pip * Decimal("3.7"), reference + pip * Decimal("4.4"), reference + pip * Decimal("2.8")),
                # Declared sell-side liquidity at the confirmed 1.6-pip swing low is swept.
                (reference + pip * Decimal("3.7"), reference + pip * Decimal("2.3"), reference + pip * Decimal("3.9"), reference + pip * Decimal("0.9")),
                # Post-sweep close breaks the prior local swing high.
                (reference + pip * Decimal("2.3"), reference + pip * Decimal("5.2"), reference + pip * Decimal("5.6"), reference + pip * Decimal("2.1")),
                # Pullback holds the broken structure and resumes upward.
                (reference + pip * Decimal("4.8"), reference + pip * Decimal("5.4"), reference + pip * Decimal("5.8"), reference + pip * Decimal("4.2")),
            ]
        else:
            values = [
                (reference, reference - pip * Decimal("0.2"), reference + pip * Decimal("0.5"), reference - pip * Decimal("0.5")),
                (reference - pip * Decimal("0.2"), reference - pip * Decimal("2.5"), reference, reference - pip * Decimal("2.9")),
                (reference - pip * Decimal("2.5"), reference - pip * Decimal("4.0"), reference - pip * Decimal("2.2"), reference - pip * Decimal("4.4")),
                (reference - pip * Decimal("4.0"), reference - pip * Decimal("4.4"), reference - pip * Decimal("3.5"), reference - pip * Decimal("5.0")),
                (reference - pip * Decimal("4.4"), reference - pip * Decimal("3.2"), reference - pip * Decimal("2.1"), reference - pip * Decimal("4.7")),
                (reference - pip * Decimal("3.2"), reference - pip * Decimal("4.2"), reference - pip * Decimal("2.8"), reference - pip * Decimal("4.8")),
                (reference - pip * Decimal("4.2"), reference - pip * Decimal("3.0"), reference - pip * Decimal("1.6"), reference - pip * Decimal("4.4")),
                (reference - pip * Decimal("3.0"), reference - pip * Decimal("4.0"), reference - pip * Decimal("2.7"), reference - pip * Decimal("4.6")),
                (reference - pip * Decimal("4.0"), reference - pip * Decimal("3.3"), reference - pip * Decimal("2.4"), reference - pip * Decimal("4.3")),
                (reference - pip * Decimal("3.3"), reference - pip * Decimal("4.1"), reference - pip * Decimal("2.9"), reference - pip * Decimal("4.9")),
                (reference - pip * Decimal("4.1"), reference - pip * Decimal("3.7"), reference - pip * Decimal("2.8"), reference - pip * Decimal("4.4")),
                (reference - pip * Decimal("3.7"), reference - pip * Decimal("2.3"), reference - pip * Decimal("0.9"), reference - pip * Decimal("3.9")),
                (reference - pip * Decimal("2.3"), reference - pip * Decimal("5.2"), reference - pip * Decimal("2.1"), reference - pip * Decimal("5.6")),
                (reference - pip * Decimal("4.8"), reference - pip * Decimal("5.4"), reference - pip * Decimal("4.2"), reference - pip * Decimal("5.8")),
            ]
        for offset, (open_price, close, high, low) in enumerate(values):
            candles[-14 + offset] = Candle(times[offset], open_price, high, low, close, vol + offset * 20)
