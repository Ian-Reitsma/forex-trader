from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Callable
from uuid import NAMESPACE_URL, uuid5

import httpx

from forex_trader.domain.context import HealthState, ProviderHealth
from forex_trader.domain.macro_history import MacroObservation
from forex_trader.infrastructure.source_evidence_repository import SourceEvidenceRepository
from forex_trader.infrastructure.trading_repository import TradingRepository
from forex_trader.ingestion.trading_economics import (
    TRADING_ECONOMICS_SOURCE,
    TradingEconomicsApiError,
    TradingEconomicsCalendarClient,
    TradingEconomicsRateLimitedError,
    TradingEconomicsSettings,
)


@dataclass(frozen=True, slots=True)
class TradingEconomicsSyncReport:
    started_at: datetime
    finished_at: datetime
    windows_requested: int
    rows_received: int
    eligible_events: int
    observations_inserted: int
    observations_existing: int
    raw_payloads_inserted: int
    currencies: tuple[str, ...]
    categories: dict[str, int]
    skipped: dict[str, int]

    def to_jsonable(self) -> dict[str, object]:
        return {
            "provider": TRADING_ECONOMICS_SOURCE.source_id,
            "authority": TRADING_ECONOMICS_SOURCE.authority.value,
            "started_at": self.started_at.isoformat(),
            "finished_at": self.finished_at.isoformat(),
            "windows_requested": self.windows_requested,
            "rows_received": self.rows_received,
            "eligible_events": self.eligible_events,
            "observations_inserted": self.observations_inserted,
            "observations_existing": self.observations_existing,
            "raw_payloads_inserted": self.raw_payloads_inserted,
            "currencies": list(self.currencies),
            "categories": dict(sorted(self.categories.items())),
            "skipped": dict(sorted(self.skipped.items())),
            "point_in_time_policy": (
                "prospective-first-seen: release availability is the local retrieval timestamp; "
                "historical vendor snapshots are never backdated into the decision ledger"
            ),
        }


def sync_trading_economics_fundamentals(
    database_path: str | Path,
    settings: TradingEconomicsSettings,
    *,
    as_of: datetime | None = None,
    client_factory: Callable[[TradingEconomicsSettings], TradingEconomicsCalendarClient] | None = None,
) -> TradingEconomicsSyncReport:
    """Fetch recent licensed calendar data and append first-seen release observations.

    This is intentionally prospective. Even when the vendor row describes an older release,
    the resulting MacroObservation becomes available at the time this process first retrieved
    it. That prevents a current API response from leaking revised historical information into
    an earlier backtest timestamp.
    """
    settings.validate()
    started = (as_of or datetime.now(UTC)).astimezone(UTC)
    trading_repository = TradingRepository(database_path)
    source_repository = SourceEvidenceRepository(database_path)
    existing_sources = {
        observation.source
        for observation in trading_repository.macro_observations()
        if observation.source.startswith("trading_economics:")
    }
    rows_received = 0
    eligible_events = 0
    observations_inserted = 0
    observations_existing = 0
    raw_payloads_inserted = 0
    windows_requested = 0
    currencies: set[str] = set()
    categories: dict[str, int] = {}
    skipped: dict[str, int] = {}
    factory = client_factory or (lambda configured: TradingEconomicsCalendarClient(configured))
    start_date = started.date() - timedelta(days=settings.history_days - 1)
    end_date = started.date()

    try:
        with factory(settings) as calendar:
            for window_start, window_end in _date_windows(start_date, end_date, settings.window_days):
                windows_requested += 1
                snapshot = calendar.fetch_calendar(window_start, window_end, retrieved_at=started)
                rows_received += snapshot.rows_received
                if source_repository.save_payload(snapshot.payload):
                    raw_payloads_inserted += 1
                for reason, count in snapshot.skipped.items():
                    skipped[reason] = skipped.get(reason, 0) + count
                eligible_events += len(snapshot.events)
                for event in snapshot.events:
                    if event.source_key in existing_sources:
                        observations_existing += 1
                        continue
                    observation = MacroObservation.release(
                        currency=event.currency,
                        category=event.category,
                        actual=event.actual,
                        forecast=event.forecast,
                        previous=event.previous,
                        higher_is_positive=event.higher_is_positive,
                        importance=event.importance,
                        available_at=started,
                        source=event.source_key,
                        observation_id=uuid5(NAMESPACE_URL, f"forex-trader:{event.source_key}"),
                    )
                    trading_repository.save_macro_observation(observation)
                    existing_sources.add(event.source_key)
                    observations_inserted += 1
                    currencies.add(event.currency)
                    categories[event.category] = categories.get(event.category, 0) + 1
    except TradingEconomicsRateLimitedError as exc:
        source_repository.save_health(
            ProviderHealth(
                TRADING_ECONOMICS_SOURCE.source_id,
                HealthState.DEGRADED,
                started,
                rate_limited=True,
                detail=str(exc),
            )
        )
        raise
    except (TradingEconomicsApiError, httpx.HTTPError, ValueError) as exc:
        source_repository.save_health(
            ProviderHealth(
                TRADING_ECONOMICS_SOURCE.source_id,
                HealthState.UNAVAILABLE,
                started,
                detail=f"{type(exc).__name__}: {exc}",
            )
        )
        raise
    source_repository.save_health(
        ProviderHealth(
            TRADING_ECONOMICS_SOURCE.source_id,
            HealthState.HEALTHY,
            started,
            detail=(
                f"calendar sync succeeded: rows={rows_received} eligible={eligible_events} "
                f"inserted={observations_inserted}"
            ),
        )
    )
    finished = datetime.now(UTC)
    return TradingEconomicsSyncReport(
        started_at=started,
        finished_at=finished,
        windows_requested=windows_requested,
        rows_received=rows_received,
        eligible_events=eligible_events,
        observations_inserted=observations_inserted,
        observations_existing=observations_existing,
        raw_payloads_inserted=raw_payloads_inserted,
        currencies=tuple(sorted(currencies)),
        categories=categories,
        skipped=skipped,
    )


def _date_windows(start: date, end: date, window_days: int) -> tuple[tuple[date, date], ...]:
    if end < start:
        raise ValueError("end cannot precede start")
    if window_days < 1:
        raise ValueError("window_days must be positive")
    windows: list[tuple[date, date]] = []
    cursor = start
    while cursor <= end:
        window_end = min(end, cursor + timedelta(days=window_days - 1))
        windows.append((cursor, window_end))
        cursor = window_end + timedelta(days=1)
    return tuple(windows)
