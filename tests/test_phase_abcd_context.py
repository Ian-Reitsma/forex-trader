from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

import pytest

from forex_trader.domain.context import (
    ConfirmationCategory,
    CrossAssetContext,
    CrossAssetSignal,
    CurrencyHorizonVector,
    CurrencyVectorComponents,
    DataQualitySnapshot,
    FlowRequirement,
    FundamentalHorizon,
    HealthState,
    MarketRegime,
    PairFundamentalContext,
    PolicyAuthority,
    ProviderHealth,
    ReadinessPolicy,
    StrategyPolicyRegistry,
    classify_regime,
    confirmation_evidence,
)
from forex_trader.domain.enums import Direction
from forex_trader.domain.models import FundamentalAssessment, Quote, TechnicalAssessment
from forex_trader.domain.sessions import SessionPhase

NOW = datetime(2026, 8, 7, 14, 0, tzinfo=UTC)


def technical(*, trend: str = "0.9", flow: str = "0.3", flow_source: str = "broker_tick_proxy") -> TechnicalAssessment:
    return TechnicalAssessment(
        instrument="EUR_USD",
        direction=Direction.LONG,
        score=Decimal("0.90"),
        atr=Decimal("0.001"),
        rsi=Decimal("55"),
        entry_reference=Decimal("1.1000"),
        stop_reference=Decimal("1.0950"),
        take_profit_reference=Decimal("1.1100"),
        reasons=(),
        signal_time=NOW,
        liquidity_sweep=True,
        trend_strength=Decimal(trend),
        setup_state="entry_confirmed",
        structure_shift=True,
        retest_confirmed=True,
        location_score=Decimal("0.8"),
        flow_pressure=Decimal(flow),
        flow_source=flow_source,
    )


def fundamental(*, differential: str = "0.2", confidence: str = "0.8") -> FundamentalAssessment:
    return FundamentalAssessment(
        instrument="EUR_USD",
        base_score=Decimal("0.2"),
        quote_score=Decimal("0"),
        differential=Decimal(differential),
        confidence=Decimal(confidence),
        reasons=(),
    )


def quote() -> Quote:
    return Quote("EUR_USD", Decimal("1.1000"), Decimal("1.1001"), NOW)


def test_readiness_healthy_degraded_and_hard_failures() -> None:
    policy = ReadinessPolicy()
    snapshot = DataQualitySnapshot(NOW)
    healthy = policy.evaluate(snapshot)
    assert healthy.ready and not healthy.reasons

    degraded = ProviderHealth("news", HealthState.DEGRADED, NOW, rate_limited=True)
    result = policy.evaluate(snapshot, [degraded])
    assert result.ready and result.degraded_sources == ("news",)

    unavailable = ProviderHealth("broker", HealthState.UNAVAILABLE, NOW)
    failed = policy.evaluate(snapshot, [unavailable])
    assert not failed.ready
    assert "PROVIDER_UNAVAILABLE:broker" in failed.reasons


def test_readiness_detects_all_material_data_failures() -> None:
    policy = ReadinessPolicy(maximum_missing_bars=0)
    snapshot = DataQualitySnapshot(
        NOW,
        quote_age_seconds=Decimal("6"),
        candle_watermark_age_seconds=Decimal("500"),
        missing_bars=2,
        timestamp_reversal=True,
        broker_transaction_lag_seconds=Decimal("20"),
        account_snapshot_age_seconds=Decimal("11"),
        cross_source_divergence_pips=Decimal("3"),
        calendar_age_seconds=Decimal("30000"),
        fundamental_source_age_seconds=Decimal("30000"),
        flow_source_age_seconds=Decimal("70"),
        clock_offset_seconds=Decimal("3"),
        reconciliation_ready=False,
    )
    result = policy.evaluate(
        snapshot,
        require_calendar=True,
        require_fundamentals=True,
        require_flow=True,
        require_reconciliation=True,
    )
    assert not result.ready
    joined = "|".join(result.reasons)
    for code in (
        "QUOTE_STALE",
        "CANDLE_WATERMARK_STALE",
        "MISSING_BARS",
        "TIMESTAMP_REVERSAL",
        "BROKER_TRANSACTION_LAG",
        "ACCOUNT_SNAPSHOT_STALE",
        "PROVIDER_DIVERGENCE",
        "CALENDAR_STALE",
        "FUNDAMENTAL_SOURCE_STALE",
        "FLOW_SOURCE_STALE",
        "CLOCK_OFFSET",
        "RECONCILIATION_NOT_READY",
    ):
        assert code in joined


def test_context_models_reject_invalid_values() -> None:
    naive = datetime(2026, 8, 7)
    with pytest.raises(ValueError):
        ProviderHealth("x", HealthState.HEALTHY, naive)
    with pytest.raises(ValueError):
        ProviderHealth("x", HealthState.HEALTHY, NOW, heartbeat_age_seconds=Decimal("-1"))
    with pytest.raises(ValueError):
        DataQualitySnapshot(NOW, missing_bars=-1)
    with pytest.raises(ValueError):
        DataQualitySnapshot(NOW, quote_age_seconds=Decimal("-1"))


def test_confirmation_categories_are_independent() -> None:
    evidence = confirmation_evidence(
        technical(),
        fundamental(),
        quote(),
        spread_limit_pips=Decimal("2"),
        pip_size=Decimal("0.0001"),
        cross_asset_alignment=Decimal("0.4"),
    )
    assert evidence.categories == frozenset(
        {
            ConfirmationCategory.PRICE,
            ConfirmationCategory.FLOW,
            ConfirmationCategory.FUNDAMENTAL,
            ConfirmationCategory.CROSS_ASSET,
            ConfirmationCategory.EXECUTION,
        }
    )
    assert evidence.independent_confirmation_count == 5
    assert evidence.independent_source_count == 5
    assert evidence.satisfies(4, 4)

    weak = confirmation_evidence(
        technical(flow="0.1", flow_source="none"),
        fundamental(differential="-0.2", confidence="0.4"),
        Quote("EUR_USD", Decimal("1.1000"), Decimal("1.1004"), NOW),
        spread_limit_pips=Decimal("2"),
        pip_size=Decimal("0.0001"),
    )
    assert weak.categories == frozenset({ConfirmationCategory.PRICE})
    assert not weak.satisfies(2, 2)


def test_currency_horizon_vectors_preserve_pair_orientation() -> None:
    base = CurrencyHorizonVector(
        "EUR",
        FundamentalHorizon.SESSION,
        CurrencyVectorComponents(policy=Decimal("0.8"), growth=Decimal("0.4")),
        Decimal("0.8"),
        Decimal("0.9"),
        NOW,
    )
    quote_vector = CurrencyHorizonVector(
        "USD",
        FundamentalHorizon.SESSION,
        CurrencyVectorComponents(policy=Decimal("-0.4")),
        Decimal("0.8"),
        Decimal("0.9"),
        NOW,
    )
    pair = PairFundamentalContext("EUR_USD", FundamentalHorizon.SESSION, base, quote_vector)
    assert pair.differential > 0
    assert pair.confidence == Decimal("0.8")
    assert CurrencyVectorComponents(policy=Decimal("4")).bounded_mean() <= Decimal("1")


def test_currency_and_cross_asset_validation_and_alignment() -> None:
    with pytest.raises(ValueError):
        CurrencyHorizonVector("EUR", FundamentalHorizon.IMMEDIATE, CurrencyVectorComponents(), Decimal("1.1"), Decimal("1"), NOW)
    with pytest.raises(ValueError):
        CrossAssetSignal("yield", Decimal("2"), Decimal("1"), "rates", NOW)
    first = CrossAssetSignal("yield", Decimal("1"), Decimal("1"), "rates", NOW)
    second = CrossAssetSignal("equity", Decimal("-1"), Decimal("0.5"), "equity", NOW)
    assert CrossAssetContext((first, second)).alignment == Decimal("0.3333333333333333333333333333")
    assert CrossAssetContext().alignment == 0


def test_regime_priority_and_policy_registry() -> None:
    assert classify_regime(technical(), phase=SessionPhase.ROLLOVER).regime is MarketRegime.ROLLOVER
    assert classify_regime(technical(), phase=SessionPhase.NEW_YORK_OPEN, execution_degraded=True).regime is MarketRegime.DISORDERLY
    assert classify_regime(technical(), phase=SessionPhase.NEW_YORK_OPEN, event_risk=True).regime is MarketRegime.PRE_EVENT
    assert classify_regime(technical(), phase=SessionPhase.NEW_YORK_OPEN, seconds_since_event=60).regime is MarketRegime.POST_EVENT_IMPULSE
    assert classify_regime(technical(), phase=SessionPhase.NEW_YORK_OPEN, seconds_since_event=600).regime is MarketRegime.POST_EVENT_NORMALIZED
    assert classify_regime(technical(trend="0.9"), phase=SessionPhase.NEW_YORK_OPEN).regime is MarketRegime.TREND
    assert classify_regime(technical(trend="0.2"), phase=SessionPhase.NEW_YORK_OPEN).regime is MarketRegime.RANGE
    assert classify_regime(technical(trend="0.5"), phase=SessionPhase.NEW_YORK_OPEN).regime is MarketRegime.TRANSITION

    registry = StrategyPolicyRegistry()
    practice = registry.select(MarketRegime.TREND, maximum_authority=PolicyAuthority.PRACTICE)
    assert practice is not None and practice.name == "sweep_reclaim"
    shadow_news = registry.select(MarketRegime.POST_EVENT_NORMALIZED, maximum_authority=PolicyAuthority.SHADOW)
    assert shadow_news is not None
    assert shadow_news.name == "post_news_continuation"
    assert shadow_news.flow_requirement is FlowRequirement.REQUIRED
    assert registry.select(MarketRegime.ROLLOVER) is None
