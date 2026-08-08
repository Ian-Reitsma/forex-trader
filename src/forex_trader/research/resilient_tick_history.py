from __future__ import annotations

from pathlib import Path

from forex_trader.research.public_history import DukascopyHistoryClient


class ResilientDukascopyHistoryClient(DukascopyHistoryClient):
    """Dukascopy history client tuned for multi-week research campaigns.

    Historical hourly files occasionally return transient 5xx responses. Keep the
    source fail-closed, but use fewer concurrent hourly requests, a longer timeout,
    and a materially longer retry horizon before declaring the archive unavailable.
    """

    def __init__(
        self,
        *,
        cache_dir: str | Path = ".cache/forex-trader/dukascopy",
        timeout_seconds: float = 45.0,
        max_concurrency: int = 4,
        retries: int = 8,
    ) -> None:
        super().__init__(
            cache_dir=cache_dir,
            timeout_seconds=max(timeout_seconds, 45.0),
            max_concurrency=min(max_concurrency, 4),
            retries=max(retries, 8),
        )
