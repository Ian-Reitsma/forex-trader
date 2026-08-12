from __future__ import annotations

import hmac
from collections.abc import Iterator
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from threading import Lock
from typing import cast

from fastapi import Depends, FastAPI, Header, HTTPException, Query, status
from fastapi.responses import FileResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from forex_trader import __version__
from forex_trader.application.engine import TradingEngine
from forex_trader.application.operations import OperationalRepository, OperationalTelemetryService
from forex_trader.application.readiness import assess_engine_readiness
from forex_trader.application.runtime_diagnostics import (
    basic_readiness_contract,
    breaker_snapshot,
    eligibility_layers,
    provider_snapshot,
)
from forex_trader.domain.models import jsonable
from forex_trader.domain.operations import OperationalCategory, OperationalSeverity


class ReleaseInput(BaseModel):
    currency: str = Field(min_length=3, max_length=3)
    category: str
    actual: Decimal
    forecast: Decimal
    previous: Decimal
    higher_is_positive: bool = True
    importance: Decimal = Field(default=Decimal("1"), ge=0, le=1)
    observed_at: datetime | None = None
    source: str = "manual"


class NewsInput(BaseModel):
    currency: str = Field(min_length=3, max_length=3)
    headline: str = Field(min_length=1)
    body: str = ""
    source_weight: Decimal = Field(default=Decimal("0.7"), ge=0, le=1)
    observed_at: datetime | None = None
    source: str = "manual"


class CentralBankInput(BaseModel):
    currency: str = Field(min_length=3, max_length=3)
    headline: str = Field(min_length=1)
    body: str = ""
    source_weight: Decimal = Field(default=Decimal("0.9"), ge=0, le=1)
    observed_at: datetime | None = None
    source: str = "official-central-bank"


class ScheduledEventInput(BaseModel):
    currency: str = Field(min_length=3, max_length=3)
    scheduled_at: datetime
    name: str = Field(min_length=1)
    importance: str = "high"
    source: str = "manual"
    pre_blackout_minutes: int = Field(default=15, ge=0, le=240)
    post_blackout_minutes: int = Field(default=5, ge=0, le=240)


def create_app(
    engine: TradingEngine,
    *,
    api_token: str | None = None,
    allow_unsafe_local_mutations: bool = False,
) -> FastAPI:
    """Create the operator API and observational trading cockpit.

    Production/exposed deployments must provide a bearer token. The explicit
    `allow_unsafe_local_mutations` escape hatch exists only for local tests and
    loopback development; the CLI never enables it for a non-loopback bind.
    """
    app = FastAPI(title="Forex Trader Control API", version=__version__)
    operations = OperationalTelemetryService(cast(OperationalRepository, engine.repository))
    repository_api_lock = Lock()

    def require_auth(authorization: str | None = Header(default=None)) -> None:
        if api_token is None:
            if allow_unsafe_local_mutations:
                return
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="control API is disabled until FOREX_API_TOKEN is configured",
            )
        expected = f"Bearer {api_token}"
        if authorization is None or not hmac.compare_digest(authorization, expected):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="valid bearer authorization is required",
                headers={"WWW-Authenticate": "Bearer"},
            )

    def serialize_repository_access() -> Iterator[None]:
        """Serialize request paths that share the runtime's single SQLite connection."""
        with repository_api_lock:
            yield

    protected = [Depends(require_auth)]
    repository_protected = [Depends(require_auth), Depends(serialize_repository_access)]

    @app.get("/health")
    @app.get("/health/live")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/health/ready", dependencies=[Depends(serialize_repository_access)])
    def readiness_health(instrument: str = "EUR_USD") -> dict[str, object]:
        contract = basic_readiness_contract()
        try:
            snapshot, providers, readiness = assess_engine_readiness(engine, instrument)
        except (ValueError, RuntimeError) as exc:
            raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc)) from exc
        if not readiness.ready:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail={
                    "ready": False,
                    "reasons": readiness.reasons,
                    "degraded_sources": readiness.degraded_sources,
                    "snapshot": jsonable(snapshot),
                    "providers": jsonable(providers),
                    **contract,
                },
            )
        return {
            "ready": True,
            "reasons": readiness.reasons,
            "degraded_sources": readiness.degraded_sources,
            "snapshot": jsonable(snapshot),
            "providers": jsonable(providers),
            **contract,
        }

    @app.get("/v1/status", dependencies=repository_protected)
    def system_status() -> dict[str, object]:
        return engine.status()

    @app.get("/v1/runtime", dependencies=repository_protected)
    def runtime_status() -> dict[str, object]:
        return engine.runtime_status()

    @app.get("/v1/account", dependencies=protected)
    def account() -> dict[str, object]:
        return jsonable(engine.broker.account())

    @app.get("/v1/positions", dependencies=protected)
    def positions() -> list[dict[str, object]]:
        return [jsonable(position) for position in engine.broker.positions()]

    @app.get("/v1/providers", dependencies=protected)
    def providers() -> dict[str, object]:
        return provider_snapshot(engine)

    @app.get("/v1/risk/breaker", dependencies=repository_protected)
    def risk_breaker() -> dict[str, object]:
        return breaker_snapshot(engine)

    @app.get("/v1/market/{instrument}/quote", dependencies=protected)
    def market_quote(instrument: str) -> dict[str, object]:
        try:
            return jsonable(engine.market_data.quote(instrument.upper()))
        except (ValueError, RuntimeError) as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.get("/v1/market/{instrument}/candles", dependencies=protected)
    def market_candles(
        instrument: str,
        granularity: str = "M5",
        count: int = Query(default=200, ge=20, le=500),
    ) -> list[dict[str, object]]:
        try:
            candles = engine.market_data.candles(instrument.upper(), granularity.upper(), count)
            return [jsonable(candle) for candle in candles]
        except (ValueError, RuntimeError) as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.get("/v1/readiness/{instrument}", dependencies=repository_protected)
    def runtime_readiness(instrument: str) -> dict[str, object]:
        try:
            snapshot, providers, readiness = assess_engine_readiness(engine, instrument)
            layers = eligibility_layers(engine, instrument, observed_at=snapshot.observed_at)
        except (ValueError, RuntimeError) as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return {
            "instrument": instrument.upper(),
            "ready": readiness.ready,
            "reasons": readiness.reasons,
            "degraded_sources": readiness.degraded_sources,
            "snapshot": jsonable(snapshot),
            "providers": jsonable(providers),
            "eligibility_layers": layers,
            **basic_readiness_contract(),
        }

    @app.get("/v1/operations/summary", dependencies=repository_protected)
    def operations_summary(hours: int = 24) -> dict[str, object]:
        try:
            return jsonable(operations.snapshot(hours=hours))
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.get("/v1/operations/events", dependencies=repository_protected)
    def operations_events(
        limit: int = 200,
        hours: int = 24,
        category: str | None = None,
        severity: str | None = None,
    ) -> list[dict[str, object]]:
        try:
            category_filter = None if category is None else OperationalCategory(category.lower())
            severity_filter = None if severity is None else OperationalSeverity(severity.lower())
            return [
                jsonable(event)
                for event in operations.events(
                    limit=limit,
                    hours=hours,
                    category=category_filter,
                    severity=severity_filter,
                )
            ]
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.get("/v1/operations/metrics", dependencies=repository_protected, response_class=PlainTextResponse)
    def operations_metrics(hours: int = 24) -> PlainTextResponse:
        try:
            return PlainTextResponse(
                operations.prometheus(hours=hours),
                media_type="text/plain; version=0.0.4; charset=utf-8",
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.get("/v1/promotion", dependencies=repository_protected)
    def promotion() -> dict[str, object]:
        return engine.promotion_status()

    @app.get("/v1/decisions", dependencies=repository_protected)
    def decisions(limit: int = Query(default=20, ge=1, le=250)) -> list[dict[str, object]]:
        return engine.repository.recent_traces(limit)

    @app.get("/v1/fundamentals/snapshots", dependencies=protected)
    def fundamental_snapshots() -> list[dict[str, object]]:
        return [jsonable(item) for item in engine.fundamentals.snapshots()]

    @app.get("/v1/fundamentals/history", dependencies=repository_protected)
    def fundamental_history() -> list[dict[str, object]]:
        if not hasattr(engine.repository, "macro_observations"):
            return []
        return [jsonable(item) for item in engine.repository.macro_observations()]  # type: ignore[attr-defined]

    @app.get("/v1/events/scheduled", dependencies=repository_protected)
    def scheduled_events() -> list[dict[str, object]]:
        if not hasattr(engine.repository, "scheduled_events"):
            return []
        return [jsonable(item) for item in engine.repository.scheduled_events()]  # type: ignore[attr-defined]

    @app.post("/v1/fundamentals/releases", dependencies=repository_protected)
    def ingest_release(payload: ReleaseInput) -> dict[str, object]:
        state = engine.ingest_release(**payload.model_dump())
        return jsonable(state)

    @app.post("/v1/fundamentals/news", dependencies=repository_protected)
    def ingest_news(payload: NewsInput) -> dict[str, object]:
        state = engine.ingest_news(**payload.model_dump())
        return jsonable(state)

    @app.post("/v1/fundamentals/central-bank", dependencies=repository_protected)
    def ingest_central_bank(payload: CentralBankInput) -> dict[str, object]:
        state = engine.ingest_central_bank(**payload.model_dump())
        return jsonable(state)

    @app.post("/v1/events/scheduled", dependencies=repository_protected)
    def ingest_scheduled_event(payload: ScheduledEventInput) -> dict[str, object]:
        event = engine.ingest_scheduled_event(**payload.model_dump())
        return jsonable(event)

    @app.post("/v1/evaluate/{instrument}", dependencies=repository_protected)
    def evaluate(instrument: str, execute: bool = False) -> dict[str, object]:
        try:
            return jsonable(engine.evaluate(instrument, execute=execute))
        except (ValueError, RuntimeError) as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.post("/v1/halts/{name}/clear", dependencies=repository_protected)
    def clear_halt(name: str) -> dict[str, str]:
        engine.clear_halt(name)
        return {"status": "cleared", "name": name}

    _mount_frontend(app)
    return app


def _mount_frontend(app: FastAPI) -> None:
    frontend = Path(__file__).resolve().parents[1] / "frontend"
    index = frontend / "index.html"
    if not index.is_file():
        return

    app.mount("/assets", StaticFiles(directory=frontend), name="frontend-assets")

    @app.get("/", include_in_schema=False)
    def trading_cockpit() -> FileResponse:
        return FileResponse(index)

    @app.get("/news", include_in_schema=False)
    def news_intelligence() -> FileResponse:
        return FileResponse(index)
