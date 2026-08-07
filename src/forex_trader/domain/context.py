from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from enum import StrEnum
from typing import Iterable

from forex_trader.domain.enums import Direction
from forex_trader.domain.models import FundamentalAssessment, Quote, TechnicalAssessment
from forex_trader.domain.sessions import SessionPhase


class HealthState(StrEnum):
    HEALTHY = "healthy"
    DEGRADED = "degraded"
    UNAVAILABLE = "unavailable"


@dataclass(frozen=True, slots=True)
class ProviderHealth:
    provider: str
    state: HealthState
    observed_at: datetime
    heartbeat_age_seconds: Decimal = Decimal("0")
    rate_limited: bool = False
    detail: str = ""

    def __post_init__(self) -> None:
        if self.observed_at.tzinfo is None:
            raise ValueError("provider health time must be timezone-aware")
        if self.heartbeat_age_seconds < 0:
            raise ValueError("heartbeat age cannot be negative")


@dataclass(frozen=True, slots=True)
class DataQualitySnapshot:
    observed_at: datetime
    quote_age_seconds: Decimal = Decimal("0")
    candle_watermark_age_seconds: Decimal = Decimal("0")
    missing_bars: int = 0
    timestamp_reversal: bool = False
    broker_transaction_lag_seconds: Decimal = Decimal("0")
    account_snapshot_age_seconds: Decimal = Decimal("0")
    cross_source_divergence_pips: Decimal = Decimal("0")
    calendar_age_seconds: Decimal = Decimal("0")
    fundamental_source_age_seconds: Decimal = Decimal("0")
    flow_source_age_seconds: Decimal = Decimal("0")
    clock_offset_seconds: Decimal = Decimal("0")
    reconciliation_ready: bool = True

    def __post_init__(self) -> None:
        if self.observed_at.tzinfo is None:
            raise ValueError("data quality time must be timezone-aware")
        nonnegative = (
            self.quote_age_seconds,
            self.candle_watermark_age_seconds,
            self.broker_transaction_lag_seconds,
            self.account_snapshot_age_seconds,
            self.cross_source_divergence_pips,
            self.calendar_age_seconds,
            self.fundamental_source_age_seconds,
            self.flow_source_age_seconds,
        )
        if any(value < 0 for value in nonnegative):
            raise ValueError("data quality ages/divergence cannot be negative")
        if self.missing_bars < 0:
            raise ValueError("missing_bars cannot be negative")


@dataclass(frozen=True, slots=True)
class TradingReadiness:
    ready: bool
    reasons: tuple[str, ...] = ()
    degraded_sources: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class ReadinessPolicy:
    maximum_quote_age_seconds: Decimal = Decimal("5")
    maximum_candle_watermark_age_seconds: Decimal = Decimal("420")
    maximum_broker_transaction_lag_seconds: Decimal = Decimal("15")
    maximum_account_snapshot_age_seconds: Decimal = Decimal("10")
    maximum_cross_source_divergence_pips: Decimal = Decimal("2.5")
    maximum_calendar_age_seconds: Decimal = Decimal("21600")
    maximum_fundamental_source_age_seconds: Decimal = Decimal("21600")
    maximum_flow_source_age_seconds: Decimal = Decimal("60")
    maximum_clock_offset_seconds: Decimal = Decimal("2")
    maximum_missing_bars: int = 0

    def evaluate(
        self,
        snapshot: DataQualitySnapshot,
        providers: Iterable[ProviderHealth] = (),
        *,
        require_calendar: bool = True,
        require_fundamentals: bool = True,
        require_flow: bool = False,
        require_reconciliation: bool = False,
    ) -> TradingReadiness:
        reasons: list[str] = []
        degraded: list[str] = []
        checks = (
            ("QUOTE_STALE", snapshot.quote_age_seconds, self.maximum_quote_age_seconds),
            ("CANDLE_WATERMARK_STALE", snapshot.candle_watermark_age_seconds, self.maximum_candle_watermark_age_seconds),
            ("BROKER_TRANSACTION_LAG", snapshot.broker_transaction_lag_seconds, self.maximum_broker_transaction_lag_seconds),
            ("ACCOUNT_SNAPSHOT_STALE", snapshot.account_snapshot_age_seconds, self.maximum_account_snapshot_age_seconds),
            ("PROVIDER_DIVERGENCE", snapshot.cross_source_divergence_pips, self.maximum_cross_source_divergence_pips),
        )
        for code, value, limit in checks:
            if value > limit:
                reasons.append(f"{code}:{value}>{limit}")
        if snapshot.missing_bars > self.maximum_missing_bars:
            reasons.append(f"MISSING_BARS:{snapshot.missing_bars}>{self.maximum_missing_bars}")
        if snapshot.timestamp_reversal:
            reasons.append("TIMESTAMP_REVERSAL")
        if abs(snapshot.clock_offset_seconds) > self.maximum_clock_offset_seconds:
            reasons.append(f"CLOCK_OFFSET:{snapshot.clock_offset_seconds}")
        if require_calendar and snapshot.calendar_age_seconds > self.maximum_calendar_age_seconds:
            reasons.append("CALENDAR_STALE")
        if require_fundamentals and snapshot.fundamental_source_age_seconds > self.maximum_fundamental_source_age_seconds:
            reasons.append("FUNDAMENTAL_SOURCE_STALE")
        if require_flow and snapshot.flow_source_age_seconds > self.maximum_flow_source_age_seconds:
            reasons.append("FLOW_SOURCE_STALE")
        if require_reconciliation and not snapshot.reconciliation_ready:
            reasons.append("RECONCILIATION_NOT_READY")
        for provider in providers:
            if provider.state is HealthState.UNAVAILABLE:
                reasons.append(f"PROVIDER_UNAVAILABLE:{provider.provider}")
            elif provider.state is HealthState.DEGRADED or provider.rate_limited:
                degraded.append(provider.provider)
        return TradingReadiness(not reasons, tuple(reasons), tuple(sorted(set(degraded))))


class ConfirmationCategory(StrEnum):
    PRICE = "price"
    FLOW = "flow"
    FUNDAMENTAL = "fundamental"
    CROSS_ASSET = "cross_asset"
    EXECUTION = "execution"


@dataclass(frozen=True, slots=True)
class ConfirmationEvidence:
    categories: frozenset[ConfirmationCategory] = field(default_factory=frozenset)
    source_ids: frozenset[str] = field(default_factory=frozenset)
    reasons: tuple[str, ...] = ()

    @property
    def independent_confirmation_count(self) -> int:
        return len(self.categories)

    @property
    def independent_source_count(self) -> int:
        return len(self.source_ids)

    def satisfies(self, minimum_categories: int, minimum_sources: int = 1) -> bool:
        return (
            self.independent_confirmation_count >= minimum_categories
            and self.independent_source_count >= minimum_sources
        )


def confirmation_evidence(
    technical: TechnicalAssessment,
    fundamental: FundamentalAssessment,
    quote: Quote,
    *,
    spread_limit_pips: Decimal,
    pip_size: Decimal,
    cross_asset_alignment: Decimal = Decimal("0"),
) -> ConfirmationEvidence:
    categories: set[ConfirmationCategory] = set()
    sources: set[str] = set()
    reasons: list[str] = []
    if technical.structure_shift and technical.retest_confirmed:
        categories.add(ConfirmationCategory.PRICE)
        sources.add("price")
        reasons.append("price structure shift and retest confirmed")
    if technical.flow_source not in {"", "none"} and abs(technical.flow_pressure) >= Decimal("0.20"):
        categories.add(ConfirmationCategory.FLOW)
        sources.add(technical.flow_source)
        reasons.append(f"flow pressure={technical.flow_pressure}")
    directional = (
        fundamental.differential
        if technical.direction is Direction.LONG
        else -fundamental.differential
        if technical.direction is Direction.SHORT
        else Decimal("0")
    )
    if fundamental.confidence >= Decimal("0.50") and directional >= Decimal("0"):
        categories.add(ConfirmationCategory.FUNDAMENTAL)
        sources.add("macro")
        reasons.append("fundamental context is non-conflicting with sufficient confidence")
    if cross_asset_alignment >= Decimal("0.25"):
        categories.add(ConfirmationCategory.CROSS_ASSET)
        sources.add("cross_asset")
        reasons.append(f"cross-asset alignment={cross_asset_alignment}")
    spread_pips = quote.spread / pip_size
    if spread_pips <= spread_limit_pips:
        categories.add(ConfirmationCategory.EXECUTION)
        sources.add("broker_quote")
        reasons.append(f"spread={spread_pips:.3f}p")
    return ConfirmationEvidence(frozenset(categories), frozenset(sources), tuple(reasons))


class FundamentalHorizon(StrEnum):
    IMMEDIATE = "immediate"
    SESSION = "session"
    INTRADAY = "intraday"
    BACKGROUND = "background"


@dataclass(frozen=True, slots=True)
class CurrencyVectorComponents:
    policy: Decimal = Decimal("0")
    inflation: Decimal = Decimal("0")
    labor: Decimal = Decimal("0")
    growth: Decimal = Decimal("0")
    risk_sensitivity: Decimal = Decimal("0")
    external_balance: Decimal = Decimal("0")
    terms_of_trade: Decimal = Decimal("0")
    positioning_repricing: Decimal = Decimal("0")

    def bounded_mean(self) -> Decimal:
        values = (
            self.policy,
            self.inflation,
            self.labor,
            self.growth,
            self.risk_sensitivity,
            self.external_balance,
            self.terms_of_trade,
            self.positioning_repricing,
        )
        value = sum(values, Decimal("0")) / Decimal(len(values))
        return max(Decimal("-1"), min(Decimal("1"), value))


@dataclass(frozen=True, slots=True)
class CurrencyHorizonVector:
    currency: str
    horizon: FundamentalHorizon
    components: CurrencyVectorComponents
    confidence: Decimal
    freshness: Decimal
    as_of: datetime

    def __post_init__(self) -> None:
        if self.as_of.tzinfo is None:
            raise ValueError("currency vector as_of must be timezone-aware")
        if not Decimal("0") <= self.confidence <= Decimal("1"):
            raise ValueError("confidence must be in [0,1]")
        if not Decimal("0") <= self.freshness <= Decimal("1"):
            raise ValueError("freshness must be in [0,1]")

    @property
    def score(self) -> Decimal:
        return self.components.bounded_mean() * self.confidence * self.freshness


@dataclass(frozen=True, slots=True)
class PairFundamentalContext:
    instrument: str
    horizon: FundamentalHorizon
    base: CurrencyHorizonVector
    quote: CurrencyHorizonVector
    market_repricing: Decimal = Decimal("0")
    contradictions: tuple[str, ...] = ()

    @property
    def differential(self) -> Decimal:
        return max(Decimal("-2"), min(Decimal("2"), self.base.score - self.quote.score))

    @property
    def confidence(self) -> Decimal:
        return min(self.base.confidence, self.quote.confidence)


@dataclass(frozen=True, slots=True)
class CrossAssetSignal:
    name: str
    direction: Decimal
    confidence: Decimal
    source: str
    observed_at: datetime

    def __post_init__(self) -> None:
        if self.observed_at.tzinfo is None:
            raise ValueError("cross-asset signal time must be timezone-aware")
        if not Decimal("-1") <= self.direction <= Decimal("1"):
            raise ValueError("direction must be in [-1,1]")
        if not Decimal("0") <= self.confidence <= Decimal("1"):
            raise ValueError("confidence must be in [0,1]")


@dataclass(frozen=True, slots=True)
class CrossAssetContext:
    signals: tuple[CrossAssetSignal, ...] = ()

    @property
    def alignment(self) -> Decimal:
        if not self.signals:
            return Decimal("0")
        weighted = sum((item.direction * item.confidence for item in self.signals), Decimal("0"))
        weight = sum((item.confidence for item in self.signals), Decimal("0"))
        return Decimal("0") if weight == 0 else max(Decimal("-1"), min(Decimal("1"), weighted / weight))


class MarketRegime(StrEnum):
    TREND = "trend"
    RANGE = "range"
    TRANSITION = "transition"
    PRE_EVENT = "pre_event"
    POST_EVENT_IMPULSE = "post_event_impulse"
    POST_EVENT_NORMALIZED = "post_event_normalized"
    DISORDERLY = "disorderly"
    ROLLOVER = "rollover"


@dataclass(frozen=True, slots=True)
class RegimeAssessment:
    regime: MarketRegime
    confidence: Decimal
    reasons: tuple[str, ...]


def classify_regime(
    technical: TechnicalAssessment,
    *,
    phase: SessionPhase,
    event_risk: bool = False,
    seconds_since_event: int | None = None,
    execution_degraded: bool = False,
) -> RegimeAssessment:
    if phase is SessionPhase.ROLLOVER:
        return RegimeAssessment(MarketRegime.ROLLOVER, Decimal("1"), ("rollover phase",))
    if execution_degraded:
        return RegimeAssessment(MarketRegime.DISORDERLY, Decimal("0.9"), ("execution/data quality degraded",))
    if event_risk:
        return RegimeAssessment(MarketRegime.PRE_EVENT, Decimal("0.85"), ("inside scheduled event protection window",))
    if seconds_since_event is not None and seconds_since_event >= 0:
        if seconds_since_event <= 180:
            return RegimeAssessment(MarketRegime.POST_EVENT_IMPULSE, Decimal("0.75"), ("recent event impulse window",))
        if seconds_since_event <= 1800:
            return RegimeAssessment(MarketRegime.POST_EVENT_NORMALIZED, Decimal("0.65"), ("post-event normalization window",))
    if technical.trend_strength >= Decimal("0.80"):
        return RegimeAssessment(MarketRegime.TREND, min(Decimal("1"), technical.trend_strength), ("higher-timeframe trend strength elevated",))
    if technical.trend_strength <= Decimal("0.35"):
        return RegimeAssessment(MarketRegime.RANGE, Decimal("0.65"), ("higher-timeframe trend strength muted",))
    return RegimeAssessment(MarketRegime.TRANSITION, Decimal("0.55"), ("mixed trend/range evidence",))


class FlowRequirement(StrEnum):
    REQUIRED = "required"
    OPTIONAL = "optional"
    NOT_USED = "not_used"


class PolicyAuthority(StrEnum):
    RESEARCH = "research"
    SHADOW = "shadow"
    PRACTICE = "practice"


@dataclass(frozen=True, slots=True)
class StrategyPolicy:
    name: str
    version: str
    regimes: frozenset[MarketRegime]
    authority: PolicyAuthority
    flow_requirement: FlowRequirement
    minimum_confirmations: int = 2


class StrategyPolicyRegistry:
    def __init__(self, policies: Iterable[StrategyPolicy] | None = None) -> None:
        self._policies = tuple(policies or default_strategy_policies())

    def policies(self) -> tuple[StrategyPolicy, ...]:
        return self._policies

    def select(self, regime: MarketRegime, *, maximum_authority: PolicyAuthority = PolicyAuthority.PRACTICE) -> StrategyPolicy | None:
        rank = {PolicyAuthority.RESEARCH: 0, PolicyAuthority.SHADOW: 1, PolicyAuthority.PRACTICE: 2}
        eligible = [
            item for item in self._policies
            if regime in item.regimes and rank[item.authority] <= rank[maximum_authority]
        ]
        if not eligible:
            return None
        return max(eligible, key=lambda item: (rank[item.authority], item.version, item.name))


def default_strategy_policies() -> tuple[StrategyPolicy, ...]:
    return (
        StrategyPolicy(
            "sweep_reclaim",
            "v1",
            frozenset({MarketRegime.TREND, MarketRegime.RANGE, MarketRegime.TRANSITION}),
            PolicyAuthority.PRACTICE,
            FlowRequirement.OPTIONAL,
            2,
        ),
        StrategyPolicy(
            "zone_continuation",
            "v1",
            frozenset({MarketRegime.TREND}),
            PolicyAuthority.SHADOW,
            FlowRequirement.OPTIONAL,
            2,
        ),
        StrategyPolicy(
            "breakout_retest",
            "v1",
            frozenset({MarketRegime.TREND, MarketRegime.TRANSITION}),
            PolicyAuthority.SHADOW,
            FlowRequirement.OPTIONAL,
            2,
        ),
        StrategyPolicy(
            "post_news_continuation",
            "v1",
            frozenset({MarketRegime.POST_EVENT_NORMALIZED}),
            PolicyAuthority.SHADOW,
            FlowRequirement.REQUIRED,
            3,
        ),
        StrategyPolicy(
            "post_news_failure",
            "v1",
            frozenset({MarketRegime.POST_EVENT_IMPULSE, MarketRegime.POST_EVENT_NORMALIZED}),
            PolicyAuthority.RESEARCH,
            FlowRequirement.REQUIRED,
            3,
        ),
    )
