from __future__ import annotations

import json
from datetime import UTC, datetime
from decimal import Decimal

from forex_trader.application.external_context import ExternalContextAggregator
from forex_trader.domain.component_confirmation import confirmation_evidence_for_components
from forex_trader.domain.context import ConfirmationCategory, PolicyAuthority
from forex_trader.domain.enums import Direction
from forex_trader.domain.models import FundamentalAssessment, Quote, TechnicalAssessment
from forex_trader.domain.policy_registry import CompleteStrategyPolicyRegistry
from forex_trader.ingestion.file_providers import (
    JsonCrossAssetProvider,
    JsonEconomicCalendarProvider,
    JsonNewsProvider,
    JsonOrderFlowProvider,
)


NOW = datetime(2026, 8, 8, 14, 0, tzinfo=UTC)


def technical(*, flow_source: str = "broker_tick_proxy", flow_pressure: str = "0.4") -> TechnicalAssessment:
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
        trend_strength=Decimal("0.8"),
        setup_state="entry_confirmed",
        structure_shift=True,
        retest_confirmed=True,
        location_score=Decimal("0.8"),
        flow_pressure=Decimal(flow_pressure),
        flow_source=flow_source,
    )


def fundamental() -> FundamentalAssessment:
    return FundamentalAssessment(
        instrument="EUR_USD",
        base_score=Decimal("0.2"),
        quote_score=Decimal("0"),
        differential=Decimal("0.2"),
        confidence=Decimal("0.8"),
        reasons=(),
    )


def quote() -> Quote:
    return Quote("EUR_USD", Decimal("1.1000"), Decimal("1.1001"), NOW)


def test_broker_tick_proxy_is_not_independent_institutional_flow() -> None:
    evidence = confirmation_evidence_for_components(
        technical(),
        fundamental(),
        quote(),
        spread_limit_pips=Decimal("2"),
        pip_size=Decimal("0.0001"),
    )
    assert ConfirmationCategory.FLOW not in evidence.categories
    assert "broker_tick_proxy" not in evidence.source_ids

    centralized = confirmation_evidence_for_components(
        technical(),
        fundamental(),
        quote(),
        spread_limit_pips=Decimal("2"),
        pip_size=Decimal("0.0001"),
        institutional_flow_pressure=Decimal("0.45"),
        institutional_flow_source="cme_fx_futures",
        institutional_flow_confidence=Decimal("0.9"),
    )
    assert ConfirmationCategory.FLOW in centralized.categories
    assert "cme_fx_futures" in centralized.source_ids


def test_file_backed_external_context_is_point_in_time(tmp_path) -> None:  # type: ignore[no-untyped-def]
    calendar_path = tmp_path / "calendar.json"
    calendar_path.write_text(
        json.dumps(
            {
                "metadata": [
                    {"indicator": "CPI", "currency": "USD", "directionality": "1", "unit": "%"}
                ],
                "scheduled": [
                    {
                        "event_id": "usd-cpi-known",
                        "currency": "USD",
                        "name": "CPI",
                        "scheduled_at": "2026-08-08T14:05:00Z",
                        "available_at": "2026-08-08T13:00:00Z",
                        "importance": "high",
                        "source": "licensed_calendar",
                    },
                    {
                        "event_id": "usd-cpi-future-revision",
                        "currency": "USD",
                        "name": "CPI revised schedule",
                        "scheduled_at": "2026-08-08T14:10:00Z",
                        "available_at": "2026-08-08T14:01:00Z",
                        "importance": "high",
                        "source": "licensed_calendar",
                    },
                ],
                "consensus": [
                    {
                        "indicator": "CPI",
                        "currency": "USD",
                        "consensus": "2.7",
                        "previous_known": "2.6",
                        "available_at": "2026-08-08T13:55:00Z",
                        "source": "licensed_calendar",
                    },
                    {
                        "indicator": "CPI",
                        "currency": "USD",
                        "consensus": "9.9",
                        "previous_known": "2.6",
                        "available_at": "2026-08-08T14:05:00Z",
                        "source": "future_consensus",
                    },
                ],
                "actuals": [
                    {
                        "indicator": "CPI",
                        "currency": "USD",
                        "actual": "2.8",
                        "revised_previous": "2.6",
                        "available_at": "2026-08-08T14:01:00Z",
                        "source": "licensed_calendar",
                    }
                ],
            }
        )
    )
    news_path = tmp_path / "news.json"
    news_path.write_text(
        json.dumps(
            {
                "news": [
                    {
                        "document_id": "n1",
                        "headline": "Policy headline",
                        "body": "text",
                        "source": "licensed_news",
                        "published_at": "2026-08-08T13:50:00Z",
                        "received_at": "2026-08-08T13:59:00Z",
                        "authority": "0.9",
                    },
                    {
                        "document_id": "future",
                        "headline": "Future delivery",
                        "body": "text",
                        "source": "licensed_news",
                        "published_at": "2026-08-08T13:58:00Z",
                        "received_at": "2026-08-08T14:01:00Z",
                        "authority": "0.9",
                    },
                ]
            }
        )
    )
    cross_path = tmp_path / "cross.json"
    cross_path.write_text(
        json.dumps(
            {
                "cross_asset": [
                    {
                        "instrument": "EUR_USD",
                        "name": "rates_repricing",
                        "direction": "0.5",
                        "confidence": "0.8",
                        "source": "rates_vendor",
                        "observed_at": "2026-08-08T13:59:30Z",
                    },
                    {
                        "instrument": "EUR_USD",
                        "name": "rates_repricing",
                        "direction": "-1",
                        "confidence": "1",
                        "source": "rates_vendor",
                        "observed_at": "2026-08-08T14:01:00Z",
                    },
                ]
            }
        )
    )
    flow_path = tmp_path / "flow.json"
    flow_path.write_text(
        json.dumps(
            {
                "order_flow": [
                    {
                        "instrument": "EUR_USD",
                        "source": "cme_fx_futures",
                        "observed_at": "2026-08-08T13:59:40Z",
                        "delta": "120",
                        "cumulative_delta": "500",
                        "vwap": "1.0998",
                        "point_of_control": "1.0995",
                        "directional_pressure": "0.45",
                        "confidence": "0.9",
                    },
                    {
                        "instrument": "EUR_USD",
                        "source": "cme_fx_futures",
                        "observed_at": "2026-08-08T14:00:30Z",
                        "directional_pressure": "-0.9",
                        "confidence": "1",
                    },
                ]
            }
        )
    )

    aggregator = ExternalContextAggregator(
        economic_calendar=JsonEconomicCalendarProvider(calendar_path),
        news=JsonNewsProvider(news_path),
        cross_asset=JsonCrossAssetProvider(cross_path),
        order_flow=JsonOrderFlowProvider(flow_path),
    )
    snapshot = aggregator.snapshot("EUR_USD", as_of=NOW)

    calendar = JsonEconomicCalendarProvider(calendar_path)
    scheduled = calendar.scheduled_events(
        start=NOW,
        end=datetime(2026, 8, 8, 14, 30, tzinfo=UTC),
        as_of=NOW,
    )
    assert [item.name for item in scheduled] == ["CPI"]
    assert [item.consensus for item in snapshot.consensus] == [Decimal("2.7")]
    assert not snapshot.release_actuals
    assert [item.document_id for item in snapshot.news] == ["n1"]
    assert snapshot.cross_asset_alignment == Decimal("0.5")
    assert snapshot.order_flow is not None
    assert snapshot.order_flow.directional_pressure == Decimal("0.45")
    assert snapshot.source_ids == (
        "cme_fx_futures",
        "licensed_calendar",
        "licensed_news",
        "rates_vendor",
    )


def test_order_flow_provider_fails_closed_when_snapshot_is_stale(tmp_path) -> None:  # type: ignore[no-untyped-def]
    path = tmp_path / "flow.json"
    path.write_text(
        json.dumps(
            {
                "order_flow": [
                    {
                        "instrument": "EUR_USD",
                        "source": "cme_fx_futures",
                        "observed_at": "2026-08-08T13:58:00Z",
                        "directional_pressure": "0.9",
                        "confidence": "1",
                    }
                ]
            }
        )
    )
    provider = JsonOrderFlowProvider(path, maximum_snapshot_age_seconds=Decimal("60"))
    assert provider.snapshot("EUR_USD", as_of=NOW) is None


def test_audited_registry_adds_missing_families_without_practice_authority() -> None:
    registry = CompleteStrategyPolicyRegistry()
    policies = {item.name: item for item in registry.policies()}
    assert policies["flow_divergence"].authority is PolicyAuthority.RESEARCH
    assert policies["vwap_repositioning"].authority is PolicyAuthority.RESEARCH
    assert policies["sweep_reclaim"].authority is PolicyAuthority.PRACTICE
