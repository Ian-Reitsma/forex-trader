from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from random import Random

from forex_trader.domain.instruments import pip_size_for
from forex_trader.domain.models import Candle, Quote
from forex_trader.domain.timeframes import granularity_duration

DEFAULT_SYNTHETIC_ANCHOR = datetime(2025, 1, 15, 19, 0, tzinfo=UTC)


class SyntheticMarketData:
    """Deterministic-price provider for local development and setup-path tests.

    `anchor` is the logical time at which the latest generated candle has just closed.
    OANDA-style candle timestamps represent bar starts, so the final candle begins one
    configured interval before the anchor. This keeps no-lookahead signal timestamps,
    quotes, and point-in-time fundamentals coherent across M5..M30 and H1/H4 policies.

    The default uses a fixed weekday/New-York-continuation logical clock. Synthetic market
    behavior must not change merely because CI started at a different wall-clock hour or
    crossed a weekend. Callers that need another session pass an explicit anchor. Demo
    fundamentals are seeded at this same logical time by runtime configuration.

    Quotes reuse the deepest cached series for the configured lower granularity whenever
    one exists. Runtime may request more than 200 lower bars to preserve full session/day
    liquidity; deriving the quote from a separately generated 200-bar path would otherwise
    create an artificial price mismatch in the simulator.
    """

    def __init__(
        self,
        *,
        seed: int = 7,
        direction: str = "long",
        anchor: datetime | None = None,
        quote_granularity: str = "M5",
    ) -> None:
        self.seed = seed
        self.direction = direction
        self.quote_granularity = quote_granularity.upper()
        granularity_duration(self.quote_granularity)
        anchor = DEFAULT_SYNTHETIC_ANCHOR if anchor is None else anchor
        if anchor.tzinfo is None:
            raise ValueError("synthetic anchor must be timezone-aware")
        self.anchor = anchor.astimezone(UTC)
        self._cache: dict[tuple[str, str, int], list[Candle]] = {}

    def candles(self, instrument: str, granularity: str, count: int) -> list[Candle]:
        key = (instrument, granularity.upper(), count)
        if key not in self._cache:
            self._cache[key] = self._generate(instrument, granularity.upper(), count)
        return list(self._cache[key])

    def quote(self, instrument: str) -> Quote:
        candidates = [
            (count, candles)
            for (cached_instrument, granularity, count), candles in self._cache.items()
            if cached_instrument == instrument and granularity == self.quote_granularity
        ]
        if candidates:
            candles = max(candidates, key=lambda item: item[0])[1]
        else:
            candles = self.candles(instrument, self.quote_granularity, 200)
        mid = candles[-1].close
        half = pip_size_for(instrument) * Decimal("0.45")
        return Quote(
            instrument,
            mid - half,
            mid + half,
            self.anchor + timedelta(seconds=1),
            bid_liquidity=Decimal("10000000"),
            ask_liquidity=Decimal("10000000"),
        )

    def quote_for_units(self, instrument: str, units: int | None) -> Quote:
        return self.quote(instrument)

    def _generate(self, instrument: str, granularity: str, count: int) -> list[Candle]:
        random = Random(f"{self.seed}:{instrument}:{granularity}:{self.direction}")
        step = granularity_duration(granularity)
        start = self.anchor - step * count
        base = Decimal("1.1000") if not instrument.endswith("_JPY") else Decimal("150.00")
        pip = pip_size_for(instrument)
        trend_sign = Decimal("1") if self.direction == "long" else Decimal("-1")
        higher_timeframe = step >= timedelta(hours=1)
        candles: list[Candle] = []
        price = base
        for index in range(count):
            drift = trend_sign * pip * (Decimal("0.22") if higher_timeframe else Decimal("0.08"))
            noise = Decimal(str(random.uniform(-0.18, 0.18))) * pip
            open_price = price
            close = price + drift + noise
            high = max(open_price, close) + pip * Decimal(str(random.uniform(0.25, 0.75)))
            low = min(open_price, close) - pip * Decimal(str(random.uniform(0.25, 0.75)))
            candles.append(Candle(start + step * index, open_price, high, low, close, 100 + index))
            price = close

        if not higher_timeframe and count >= 30:
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
                (reference + pip * Decimal("3.7"), reference + pip * Decimal("2.3"), reference + pip * Decimal("3.9"), reference + pip * Decimal("0.9")),
                (reference + pip * Decimal("2.3"), reference + pip * Decimal("5.2"), reference + pip * Decimal("5.6"), reference + pip * Decimal("2.1")),
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
