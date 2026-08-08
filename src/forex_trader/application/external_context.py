from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal

from forex_trader.domain.context import CrossAssetContext, ProviderHealth
from forex_trader.ingestion.providers import (
    CrossAssetProvider,
    EconomicCalendarProvider,
    NewsProvider,
    OrderFlowProvider,
    OrderFlowSnapshot,
)
from forex_trader.intelligence.events import ConsensusSnapshot, NewsDocument, ReleaseActual, ReleaseMetadata


@dataclass(frozen=True, slots=True)
class ExternalDecisionContext:
    """Exact point-in-time external inputs available for one FX evaluation."""

    instrument: str
    as_of: datetime
    consensus: tuple[ConsensusSnapshot, ...] = ()
    release_actuals: tuple[ReleaseActual, ...] = ()
    release_metadata: tuple[ReleaseMetadata, ...] = ()
    news: tuple[NewsDocument, ...] = ()
    cross_asset: CrossAssetContext = CrossAssetContext()
    order_flow: OrderFlowSnapshot | None = None
    provider_health: tuple[ProviderHealth, ...] = ()
    errors: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if self.as_of.tzinfo is None:
            raise ValueError("external decision context as_of must be timezone-aware")

    @property
    def cross_asset_alignment(self) -> Decimal:
        return self.cross_asset.alignment

    @property
    def institutional_flow_pressure(self) -> Decimal | None:
        return None if self.order_flow is None else self.order_flow.directional_pressure

    @property
    def institutional_flow_source(self) -> str | None:
        return None if self.order_flow is None else self.order_flow.source

    @property
    def institutional_flow_confidence(self) -> Decimal:
        return Decimal("0") if self.order_flow is None else self.order_flow.confidence

    @property
    def source_ids(self) -> tuple[str, ...]:
        sources = {
            *(item.source for item in self.consensus),
            *(item.source for item in self.release_actuals),
            *(item.source for item in self.news),
            *(item.source for item in self.cross_asset.signals),
        }
        if self.order_flow is not None:
            sources.add(self.order_flow.source)
        return tuple(sorted(source for source in sources if source))


class ExternalContextAggregator:
    """Collect optional data planes without allowing provider failures to fabricate evidence."""

    def __init__(
        self,
        *,
        economic_calendar: EconomicCalendarProvider | None = None,
        news: NewsProvider | None = None,
        cross_asset: CrossAssetProvider | None = None,
        order_flow: OrderFlowProvider | None = None,
        macro_lookback: timedelta = timedelta(hours=24),
        news_lookback: timedelta = timedelta(hours=6),
    ) -> None:
        self.economic_calendar = economic_calendar
        self.news_provider = news
        self.cross_asset_provider = cross_asset
        self.order_flow_provider = order_flow
        self.macro_lookback = macro_lookback
        self.news_lookback = news_lookback

    @property
    def configured(self) -> bool:
        return any(
            provider is not None
            for provider in (
                self.economic_calendar,
                self.news_provider,
                self.cross_asset_provider,
                self.order_flow_provider,
            )
        )

    def snapshot(self, instrument: str, *, as_of: datetime) -> ExternalDecisionContext:
        if as_of.tzinfo is None:
            raise ValueError("external context snapshot requires a timezone-aware as_of")
        normalized = instrument.upper()
        currencies = frozenset(normalized.split("_", maxsplit=1))
        consensus: tuple[ConsensusSnapshot, ...] = ()
        actuals: tuple[ReleaseActual, ...] = ()
        metadata: tuple[ReleaseMetadata, ...] = ()
        news: tuple[NewsDocument, ...] = ()
        cross_asset = CrossAssetContext()
        order_flow: OrderFlowSnapshot | None = None
        health: list[ProviderHealth] = []
        errors: list[str] = []

        if self.economic_calendar is not None:
            try:
                start = as_of - self.macro_lookback
                consensus = tuple(
                    item
                    for item in self.economic_calendar.consensus_snapshots(start=start, end=as_of)
                    if item.currency.upper() in currencies
                )
                actuals = tuple(
                    item
                    for item in self.economic_calendar.release_actuals(start=start, end=as_of)
                    if item.currency.upper() in currencies
                )
                metadata = tuple(
                    item for item in self.economic_calendar.release_metadata() if item.currency.upper() in currencies
                )
            except Exception as exc:
                errors.append(f"economic_calendar:{type(exc).__name__}:{str(exc)[:200]}")
            self._append_health(health, errors, "economic_calendar", self.economic_calendar)

        if self.news_provider is not None:
            try:
                news = self.news_provider.news(start=as_of - self.news_lookback, end=as_of)
            except Exception as exc:
                errors.append(f"news:{type(exc).__name__}:{str(exc)[:200]}")
            self._append_health(health, errors, "news", self.news_provider)

        if self.cross_asset_provider is not None:
            try:
                cross_asset = CrossAssetContext(self.cross_asset_provider.signals(normalized, as_of=as_of))
            except Exception as exc:
                errors.append(f"cross_asset:{type(exc).__name__}:{str(exc)[:200]}")
            self._append_health(health, errors, "cross_asset", self.cross_asset_provider)

        if self.order_flow_provider is not None:
            try:
                order_flow = self.order_flow_provider.snapshot(normalized, as_of=as_of)
            except Exception as exc:
                errors.append(f"order_flow:{type(exc).__name__}:{str(exc)[:200]}")
            self._append_health(health, errors, "order_flow", self.order_flow_provider)

        return ExternalDecisionContext(
            instrument=normalized,
            as_of=as_of,
            consensus=consensus,
            release_actuals=actuals,
            release_metadata=metadata,
            news=news,
            cross_asset=cross_asset,
            order_flow=order_flow,
            provider_health=tuple(health),
            errors=tuple(errors),
        )

    @staticmethod
    def _append_health(
        health: list[ProviderHealth],
        errors: list[str],
        label: str,
        provider: object,
    ) -> None:
        try:
            health_fn = getattr(provider, "health")
            health.append(health_fn())
        except Exception as exc:
            errors.append(f"{label}_health:{type(exc).__name__}:{str(exc)[:200]}")
