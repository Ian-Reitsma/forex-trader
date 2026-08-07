from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

from forex_trader.application.engine import TradingEngine
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


class NewsInput(BaseModel):
    currency: str = Field(min_length=3, max_length=3)
    headline: str = Field(min_length=1)
    body: str = ""
    source_weight: Decimal = Field(default=Decimal("0.7"), ge=0, le=1)
    observed_at: datetime | None = None


def create_app(engine: TradingEngine) -> FastAPI:
    app = FastAPI(title="Forex Trader Control API", version="0.2.0")

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/v1/status")
    def status() -> dict[str, object]:
        return engine.status()

    @app.get("/v1/decisions")
    def decisions(limit: int = 20) -> list[dict[str, object]]:
        return engine.repository.recent_traces(limit)

    @app.post("/v1/fundamentals/releases")
    def ingest_release(payload: ReleaseInput) -> dict[str, object]:
        state = engine.fundamentals.apply_release(**payload.model_dump())
        return jsonable(state)

    @app.post("/v1/fundamentals/news")
    def ingest_news(payload: NewsInput) -> dict[str, object]:
        state = engine.fundamentals.apply_news(**payload.model_dump())
        return jsonable(state)

    @app.post("/v1/evaluate/{instrument}")
    def evaluate(instrument: str, execute: bool = False) -> dict[str, object]:
        try:
            return jsonable(engine.evaluate(instrument, execute=execute))
        except (ValueError, RuntimeError) as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    return app
