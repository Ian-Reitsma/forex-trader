from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Callable
from uuid import NAMESPACE_URL, uuid5

from forex_trader.domain.context import HealthState, ProviderHealth
from forex_trader.domain.macro_history import MacroObservation
from forex_trader.infrastructure.source_evidence_repository import SourceEvidenceRepository
from forex_trader.infrastructure.trading_repository import TradingRepository
from forex_trader.ingestion.free_official import (
    FreeOfficialSourceError,
    OfficialCurrencySnapshot,
    OfficialWebClient,
    supported_currencies,
)
from forex_trader.ingestion.free_official_resilient import (
    ResilientOfficialWebClient,
    fetch_currency_resilient,
)


@dataclass(frozen=True, slots=True)
class FreeOfficialSyncReport:
    started_at: datetime
    finished_at: datetime
    currencies_attempted: tuple[str, ...]
    currencies_succeeded: tuple[str, ...]
    indicators_seen: int
    observations_inserted: int
    observations_existing: int
    raw_payloads_inserted: int
    components: dict[str, int]
    failures: dict[str, str]

    @property
    def healthy(self) -> bool:
        return bool(self.currencies_attempted) and len(self.currencies_succeeded) == len(self.currencies_attempted)

    @property
    def status(self) -> str:
        if self.healthy:
            return "healthy"
        if self.currencies_succeeded:
            return "degraded"
        return "unavailable"

    def to_jsonable(self) -> dict[str, object]:
        return {
            "provider": "free_official",
            "authority": "official",
            "cost": "free/no-key",
            "started_at": self.started_at.isoformat(),
            "finished_at": self.finished_at.isoformat(),
            "currencies_attempted": list(self.currencies_attempted),
            "currencies_succeeded": list(self.currencies_succeeded),
            "indicators_seen": self.indicators_seen,
            "observations_inserted": self.observations_inserted,
            "observations_existing": self.observations_existing,
            "raw_payloads_inserted": self.raw_payloads_inserted,
            "components": dict(sorted(self.components.items())),
            "failures": dict(sorted(self.failures.items())),
            "healthy": self.healthy,
            "status": self.status,
            "point_in_time_policy": (
                "prospective-first-seen official state: current official values become knowable "
                "only when locally retrieved; no paid or reconstructed consensus is invented"
            ),
        }


def sync_free_official_fundamentals(
    database_path: str | Path,
    *,
    as_of: datetime | None = None,
    currencies: tuple[str, ...] | None = None,
    client_factory: Callable[[], OfficialWebClient] | None = None,
    fetcher: Callable[[str, OfficialWebClient, datetime], OfficialCurrencySnapshot] | None = None,
) -> FreeOfficialSyncReport:
    started = (as_of or datetime.now(UTC)).astimezone(UTC)
    selected = tuple(dict.fromkeys(item.upper() for item in (currencies or supported_currencies())))
    unsupported = sorted(set(selected) - set(supported_currencies()))
    if unsupported:
        raise ValueError(f"unsupported free official currencies: {unsupported}")
    trading_repository = TradingRepository(database_path)
    source_repository = SourceEvidenceRepository(database_path)
    existing_sources = {
        observation.source
        for observation in trading_repository.macro_observations()
        if observation.source.startswith("official:")
    }
    observations_inserted = 0
    observations_existing = 0
    raw_payloads_inserted = 0
    indicators_seen = 0
    succeeded: list[str] = []
    failures: dict[str, str] = {}
    components: dict[str, int] = {}
    factory = client_factory or ResilientOfficialWebClient

    def default_fetch(currency: str, client: OfficialWebClient, observed: datetime) -> OfficialCurrencySnapshot:
        return fetch_currency_resilient(currency, client, retrieved_at=observed)

    selected_fetcher = fetcher or default_fetch
    with factory() as client:
        for currency in selected:
            health_id = f"free_official_{currency.lower()}"
            try:
                snapshot = selected_fetcher(currency, client, started)
                if snapshot.currency.upper() != currency:
                    raise ValueError(f"free official snapshot currency mismatch: expected {currency}")
                for payload in snapshot.payloads:
                    if source_repository.save_payload(payload):
                        raw_payloads_inserted += 1
                for indicator in snapshot.indicators:
                    indicators_seen += 1
                    components[indicator.category] = components.get(indicator.category, 0) + 1
                    if indicator.source_key in existing_sources:
                        observations_existing += 1
                        continue
                    observation = MacroObservation.indicator(
                        currency=indicator.currency,
                        category=indicator.category,
                        actual=indicator.actual,
                        previous=indicator.previous,
                        higher_is_positive=indicator.higher_is_positive,
                        importance=indicator.importance,
                        available_at=started,
                        source=indicator.source_key,
                        observation_id=uuid5(NAMESPACE_URL, f"forex-trader:{indicator.source_key}"),
                    )
                    trading_repository.save_macro_observation(observation)
                    existing_sources.add(indicator.source_key)
                    observations_inserted += 1
                succeeded.append(currency)
                source_repository.save_health(
                    ProviderHealth(
                        health_id,
                        HealthState.HEALTHY,
                        started,
                        detail=f"official fundamentals sync succeeded: indicators={len(snapshot.indicators)}",
                    )
                )
            except (FreeOfficialSourceError, ValueError, RuntimeError) as exc:
                detail = f"{type(exc).__name__}: {exc}"
                failures[currency] = detail
                source_repository.save_health(
                    ProviderHealth(health_id, HealthState.UNAVAILABLE, started, detail=detail)
                )

    finished = datetime.now(UTC)
    return FreeOfficialSyncReport(
        started_at=started,
        finished_at=finished,
        currencies_attempted=selected,
        currencies_succeeded=tuple(succeeded),
        indicators_seen=indicators_seen,
        observations_inserted=observations_inserted,
        observations_existing=observations_existing,
        raw_payloads_inserted=raw_payloads_inserted,
        components=components,
        failures=failures,
    )
