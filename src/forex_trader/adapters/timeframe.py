from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from datetime import UTC, datetime
from decimal import Decimal

from forex_trader.application.ports import MarketDataProvider
from forex_trader.domain.context import HealthState, ProviderHealth
from forex_trader.domain.models import Candle, Quote
from forex_trader.domain.timeframes import minimum_lower_history_count, validate_timeframe_pair


class TimeframeMappedMarketData:
    """Translate semantic lower/higher requests into the configured research policy.

    The application layer historically requests M5/H1 as semantic lower/higher aliases.
    This adapter maps them to the configured research pair. For lower-timeframe requests,
    it enforces enough completed history to reconstruct a full current FX day plus the full
    prior day.

    Within an explicit `evaluation_scope`, completed candle responses are reused by
    instrument/granularity. A larger snapshot may satisfy a later smaller request by taking
    its most recent bars. The cache is context-local and destroyed at scope exit, so it
    cannot leak stale bars across evaluations. Quotes are never cached.
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
        self._snapshot: ContextVar[dict[tuple[str, str], list[Candle]] | None] = ContextVar(
            f"forex_trader_candle_snapshot_{id(self)}",
            default=None,
        )
        self._last_quote_market_at: datetime | None = None
        self._last_quote_success_at: datetime | None = None

    @contextmanager
    def evaluation_scope(self) -> Iterator[None]:
        """Open one context-local completed-candle snapshot.

        Nested scopes intentionally share the outer snapshot. This keeps helpers called by
        one engine evaluation consistent while guaranteeing the cache is discarded before
        the next top-level evaluation.
        """
        if self._snapshot.get() is not None:
            yield
            return
        token = self._snapshot.set({})
        try:
            yield
        finally:
            self._snapshot.reset(token)

    def candles(self, instrument: str, granularity: str, count: int) -> list[Candle]:
        if count < 1:
            raise ValueError("candle count must be positive")
        requested = granularity.upper()
        if requested == "M5":
            mapped = self.lower_timeframe
            effective_count = max(count, self.minimum_lower_count)
        elif requested == "H1":
            mapped = self.higher_timeframe
            effective_count = count
        else:
            mapped = requested
            effective_count = count
        return self._candles_snapshot(instrument, mapped, effective_count)

    def quote(self, instrument: str) -> Quote:
        # Never cache executable pricing. Every quote call must reach the provider.
        quote = self.provider.quote(instrument)
        self._last_quote_market_at = quote.time
        self._last_quote_success_at = datetime.now(UTC)
        return quote

    def health(self) -> ProviderHealth:
        """Expose health of the market path most recently proven by an executable quote.

        Provider transport health and market-event timestamps are different concepts. The
        heartbeat age is measured from the successful request completion time, while the
        quote's market timestamp remains available in the detail for diagnosis. An upstream
        explicit health contract remains authoritative when one exists.
        """
        upstream_health = getattr(self.provider, "health", None)
        if callable(upstream_health):
            result = upstream_health()
            if isinstance(result, ProviderHealth):
                return result
        now = datetime.now(UTC)
        if self._last_quote_success_at is None:
            return ProviderHealth(
                provider=type(self.provider).__name__,
                state=HealthState.DEGRADED,
                observed_at=now,
                detail="no successful executable quote has been observed through the timeframe adapter",
            )
        success_at = self._last_quote_success_at.astimezone(UTC)
        age = max(Decimal("0"), Decimal(str((now - success_at).total_seconds())))
        market_at = self._last_quote_market_at.isoformat() if self._last_quote_market_at is not None else "unknown"
        return ProviderHealth(
            provider=type(self.provider).__name__,
            state=HealthState.HEALTHY,
            observed_at=success_at,
            heartbeat_age_seconds=age,
            detail=(
                "successful executable quote request observed through TimeframeMappedMarketData; "
                f"market_timestamp={market_at}"
            ),
        )

    def _candles_snapshot(self, instrument: str, granularity: str, count: int) -> list[Candle]:
        cache = self._snapshot.get()
        if cache is None:
            return self.provider.candles(instrument, granularity, count)

        key = (instrument.upper(), granularity.upper())
        cached = cache.get(key)
        if cached is not None and len(cached) >= count:
            return list(cached[-count:])

        fresh = list(self.provider.candles(instrument, granularity, count))
        if cached is None or len(fresh) >= len(cached):
            cache[key] = fresh
        return list(fresh)
