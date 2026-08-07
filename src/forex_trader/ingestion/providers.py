from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Protocol

from forex_trader.domain.context import CrossAssetSignal, ProviderHealth
from forex_trader.intelligence.events import ConsensusSnapshot, NewsDocument, ReleaseActual, ReleaseMetadata


class EconomicCalendarProvider(Protocol):
    def consensus_snapshots(self, *, start: datetime, end: datetime) -> tuple[ConsensusSnapshot, ...]: ...
    def release_actuals(self, *, start: datetime, end: datetime) -> tuple[ReleaseActual, ...]: ...
    def release_metadata(self) -> tuple[ReleaseMetadata, ...]: ...
    def health(self) -> ProviderHealth: ...


class OfficialDocumentProvider(Protocol):
    def documents(self, *, start: datetime, end: datetime) -> tuple[NewsDocument, ...]: ...
    def health(self) -> ProviderHealth: ...


class NewsProvider(Protocol):
    def news(self, *, start: datetime, end: datetime) -> tuple[NewsDocument, ...]: ...
    def health(self) -> ProviderHealth: ...


class CrossAssetProvider(Protocol):
    def signals(self, instrument: str, *, as_of: datetime) -> tuple[CrossAssetSignal, ...]: ...
    def health(self) -> ProviderHealth: ...


@dataclass(frozen=True, slots=True)
class OrderFlowSnapshot:
    instrument: str
    observed_at: datetime
    source: str
    delta: Decimal | None = None
    cumulative_delta: Decimal | None = None
    vwap: Decimal | None = None
    point_of_control: Decimal | None = None
    volume_expansion: Decimal | None = None
    absorption: Decimal | None = None
    depth_imbalance: Decimal | None = None
    confidence: Decimal = Decimal("0")

    def __post_init__(self) -> None:
        if self.observed_at.tzinfo is None:
            raise ValueError("order-flow snapshot time must be timezone-aware")
        if not Decimal("0") <= self.confidence <= Decimal("1"):
            raise ValueError("order-flow confidence must be in [0,1]")


class OrderFlowProvider(Protocol):
    def snapshot(self, instrument: str, *, as_of: datetime) -> OrderFlowSnapshot | None: ...
    def health(self) -> ProviderHealth: ...


class UnavailableOrderFlowProvider:
    """Explicit unavailable implementation; never fabricates institutional order flow."""

    def __init__(self, health: ProviderHealth) -> None:
        self._health = health

    def snapshot(self, instrument: str, *, as_of: datetime) -> OrderFlowSnapshot | None:
        return None

    def health(self) -> ProviderHealth:
        return self._health
