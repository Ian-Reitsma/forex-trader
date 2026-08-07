from __future__ import annotations

import hmac
from datetime import datetime
from decimal import Decimal

from fastapi import Depends, FastAPI, Header, HTTPException, status
from pydantic import BaseModel, Field

from forex_trader import __version__
from forex_trader.application.engine import TradingEngine
from forex_trader.application.readiness import assess_engine_readiness
from forex_trader.domain.models import jsonable


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
    """Create the operator API.

    Production/exposed deployments must provide a bearer token. The explicit
    `allow_unsafe_local_mutations` escape hatch exists only for local tests and
    loopback development; the CLI never enables it for a non-loopback bind.
    """
    app = FastAPI(title="Forex Trader Control API", version=__version__)

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

    protected = [Depends(require_auth)]

    @app.get("/health")
    @app.get("/health/live")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/health/ready")
    def readiness_health(instrument: str = "EUR_USD") -> dict[str, object]:
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
                },
            )
        return {
            "ready": True,
            "reasons": readiness.reasons,
            "degraded_sources": readiness.degraded_sources,
            "snapshot": jsonable(snapshot),
            "providers": jsonable(providers),
        }

    @app.get("/v1/status", dependencies=protected)
    def system_status() -> dict[str, object]:
        return engine.status()

    @app.get("/v1/readiness/{instrument}", dependencies=protected)
    def runtime_readiness(instrument: str) -> dict[str, object]:
        snapshot, providers, readiness = assess_engine_readiness(engine, instrument)
        return {
            "instrument": instrument.upper(),
            "ready": readiness.ready,
            "reasons": readiness.reasons,
            "degraded_sources": readiness.degraded_sources,
            "snapshot": jsonable(snapshot),
            "providers": jsonable(providers),
        }

    @app.get("/v1/promotion", dependencies=protected)
    def promotion() -> dict[str, object]:
        return engine.promotion_status()

    @app.get("/v1/decisions", dependencies=protected)
    def decisions(limit: int = 20) -> list[dict[str, object]]:
        return engine.repository.recent_traces(limit)

    @app.get("/v1/fundamentals/history", dependencies=protected)
    def fundamental_history() -> list[dict[str, object]]:
        if not hasattr(engine.repository, "macro_observations"):
            return []
        return [jsonable(item) for item in engine.repository.macro_observations()]  # type: ignore[attr-defined]

    @app.post("/v1/fundamentals/releases", dependencies=protected)
    def ingest_release(payload: ReleaseInput) -> dict[str, object]:
        state = engine.ingest_release(**payload.model_dump())
        return jsonable(state)

    @app.post("/v1/fundamentals/news", dependencies=protected)
    def ingest_news(payload: NewsInput) -> dict[str, object]:
        state = engine.ingest_news(**payload.model_dump())
        return jsonable(state)

    @app.post("/v1/fundamentals/central-bank", dependencies=protected)
    def ingest_central_bank(payload: CentralBankInput) -> dict[str, object]:
        state = engine.ingest_central_bank(**payload.model_dump())
        return jsonable(state)

    @app.post("/v1/events/scheduled", dependencies=protected)
    def ingest_scheduled_event(payload: ScheduledEventInput) -> dict[str, object]:
        event = engine.ingest_scheduled_event(**payload.model_dump())
        return jsonable(event)

    @app.post("/v1/evaluate/{instrument}", dependencies=protected)
    def evaluate(instrument: str, execute: bool = False) -> dict[str, object]:
        try:
            return jsonable(engine.evaluate(instrument, execute=execute))
        except (ValueError, RuntimeError) as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.post("/v1/halts/{name}/clear", dependencies=protected)
    def clear_halt(name: str) -> dict[str, str]:
        engine.clear_halt(name)
        return {"status": "cleared", "name": name}

    return app
