from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from uuid import uuid4

from forex_trader.domain.enums import DecisionDisposition, Direction
from forex_trader.domain.macro_history import PointInTimeFundamentalBook
from forex_trader.domain.models import CurrencyFundamentals, Quote, TechnicalAssessment, TradeCandidate
from forex_trader.domain.sessions import SessionPhase
from forex_trader.ingestion.providers import OrderFlowSnapshot
from forex_trader.research.backtest import BacktestTrade, OutcomeStatus
from forex_trader.research.portfolio_risk_replay import HistoricalPortfolioRiskConfig
from forex_trader.research.public_history import HistoricalTick
from forex_trader.research.tick_backtest import TickBacktestOpportunity
from scripts.run_staged_historical_development import (
    CausalExecution,
    FlowHistory,
    SpotHistoryIndex,
    StructuredZoneEvidence,
    _flow_history,
    _macro_book,
    evaluate_stages,
    macro_gate,
    replay_production_portfolio_risk,
)

NOW = datetime(2026, 2, 3, 14, 0, tzinfo=UTC)


def _execution(
    index: int = 0,
    *,
    aligned: bool = True,
    direction: Direction = Direction.LONG,
    r_multiple: str = "1",
) -> CausalExecution:
    decision = NOW + timedelta(hours=index * 3)
    if direction is Direction.LONG:
        entry, stop, target = Decimal("1.1001"), Decimal("1.0991"), Decimal("1.1021")
        bid, ask = Decimal("1.1000"), Decimal("1.1001")
    else:
        entry, stop, target = Decimal("1.1000"), Decimal("1.1010"), Decimal("1.0980")
        bid, ask = Decimal("1.1000"), Decimal("1.1001")
    candidate = TradeCandidate(
        candidate_id=uuid4(),
        instrument="EUR_USD",
        direction=direction,
        disposition=DecisionDisposition.TRADE,
        score=Decimal("0.75"),
        entry_price=entry,
        stop_loss=stop,
        take_profit=target,
        technical_score=Decimal("0.75"),
        fundamental_score=Decimal("0"),
        reasons=(),
        signal_time=decision,
    )
    realized = Decimal(r_multiple)
    trade = BacktestTrade(
        instrument="EUR_USD",
        direction=direction,
        signal_time=decision,
        score=Decimal("0.75"),
        status=OutcomeStatus.WIN if realized > 0 else OutcomeStatus.LOSS,
        r_multiple=realized,
        bars_held=6,
        entry_fill=entry,
        exit_fill=target if realized > 0 else stop,
    )
    entry_time = decision + timedelta(seconds=1)
    opportunity = TickBacktestOpportunity(
        instrument="EUR_USD",
        decision_time=decision,
        entry_time=entry_time,
        exit_time=decision + timedelta(minutes=30),
        trade=trade,
        technical_score=Decimal("0.75"),
        reward_risk=Decimal("2"),
        spread_pips=Decimal("1"),
        displacement=True,
        session_phase=SessionPhase.NEW_YORK_OPEN,
        news_directional=Decimal("0"),
        news_confidence=Decimal("0"),
        latest_news_age_minutes=None,
        setup_family="sweep_reclaim",
    )
    technical = TechnicalAssessment(
        instrument="EUR_USD",
        direction=direction,
        score=Decimal("0.75"),
        atr=Decimal("0.001"),
        rsi=Decimal("50"),
        entry_reference=entry,
        stop_reference=stop,
        take_profit_reference=target,
        reasons=(),
        signal_time=decision,
        liquidity_sweep=True,
        structure_shift=True,
        retest_confirmed=True,
        setup_state="entry_confirmed",
        location_score=Decimal("0.8"),
    )
    zone = StructuredZoneEvidence(
        available=True,
        aligned=aligned,
        pattern="RBR" if direction is Direction.LONG else "RBD",
        quality=Decimal("0.7"),
        distance_atr=Decimal("0.2"),
        zone_id=f"zone-{index}",
    )
    return CausalExecution(
        opportunity=opportunity,
        candidate=candidate,
        decision_quote=Quote("EUR_USD", bid, ask, decision),
        entry_quote=Quote("EUR_USD", bid, ask, entry_time),
        technical=technical,
        structured_zone=zone,
    )


def test_missing_external_sources_fail_closed_without_changing_baseline_identity() -> None:
    values = (_execution(0, aligned=True), _execution(1, aligned=False), _execution(2, aligned=True, r_multiple="-1"))
    result = evaluate_stages(
        values,
        period_start=NOW.replace(hour=0),
        period_end=NOW.replace(hour=0) + timedelta(days=2),
    )

    assert [item.identity for item in result.baseline] == [item.identity for item in values]
    assert [item.identity for item in result.structured_zone] == [values[0].identity, values[2].identity]
    assert result.baseline_metrics.selected_executions == 3
    assert result.structured_zone_metrics.selected_executions == 2
    assert result.macro_metrics.status == "unavailable"
    assert result.flow_metrics.status == "unavailable"
    assert result.macro == ()
    assert result.flow == ()


def test_macro_gate_uses_only_point_in_time_pair_state() -> None:
    execution = _execution()
    book = PointInTimeFundamentalBook(
        seeds=(
            CurrencyFundamentals(
                "EUR",
                policy=Decimal("0.8"),
                confidence=Decimal("0.8"),
                as_of=NOW - timedelta(hours=1),
            ),
            CurrencyFundamentals(
                "USD",
                policy=Decimal("0"),
                confidence=Decimal("0.8"),
                as_of=NOW - timedelta(hours=1),
            ),
        )
    )
    evidence = macro_gate(execution, book)
    assert evidence.available
    assert evidence.passed
    assert evidence.directional_support >= Decimal("0.05")

    future_only = PointInTimeFundamentalBook(
        seeds=(
            CurrencyFundamentals("EUR", policy=Decimal("1"), confidence=Decimal("1"), as_of=NOW + timedelta(hours=1)),
            CurrencyFundamentals("USD", confidence=Decimal("1"), as_of=NOW + timedelta(hours=1)),
        )
    )
    assert not macro_gate(execution, future_only).available


def test_centralized_flow_can_pass_but_broker_tick_proxy_cannot() -> None:
    execution = _execution()
    previous = OrderFlowSnapshot(
        instrument="EUR_USD",
        observed_at=NOW - timedelta(seconds=30),
        source="cme_fx_futures",
        delta=Decimal("50"),
        cumulative_delta=Decimal("1000"),
        confidence=Decimal("0.9"),
    )
    latest = OrderFlowSnapshot(
        instrument="EUR_USD",
        observed_at=NOW - timedelta(seconds=5),
        source="cme_fx_futures",
        delta=Decimal("180"),
        cumulative_delta=Decimal("1250"),
        vwap=Decimal("1.0990"),
        point_of_control=Decimal("1.0985"),
        volume_expansion=Decimal("2"),
        absorption=Decimal("0.8"),
        depth_imbalance=Decimal("0.7"),
        confidence=Decimal("0.9"),
    )
    history = FlowHistory.from_snapshots((previous, latest))
    evidence = history.assess(execution, spot_price_at=lambda _instrument, _instant: Decimal("1.1000"))
    assert evidence.available
    assert evidence.passed
    assert evidence.assessment is not None
    assert evidence.assessment.eligible_for_confirmation

    proxy = OrderFlowSnapshot(
        instrument="EUR_USD",
        observed_at=NOW - timedelta(seconds=2),
        source="broker_tick_proxy",
        delta=Decimal("999"),
        absorption=Decimal("1"),
        depth_imbalance=Decimal("1"),
        confidence=Decimal("1"),
    )
    proxy_evidence = FlowHistory.from_snapshots((proxy,)).assess(
        execution,
        spot_price_at=lambda _instrument, _instant: Decimal("1.1000"),
    )
    assert proxy_evidence.available
    assert not proxy_evidence.passed
    assert proxy_evidence.assessment is not None
    assert not proxy_evidence.assessment.eligible_for_confirmation


def test_spot_index_provides_causal_marks_conversion_and_risk_replay() -> None:
    ticks = tuple(
        HistoricalTick(
            "EUR_USD",
            NOW - timedelta(hours=100 - index),
            Decimal("1.1000"),
            Decimal("1.1002"),
        )
        for index in range(101)
    )
    jpy = tuple(
        HistoricalTick(
            "USD_JPY",
            NOW - timedelta(hours=100 - index),
            Decimal("150.00"),
            Decimal("150.02"),
        )
        for index in range(101)
    )
    spot = SpotHistoryIndex.from_ticks({"EUR_USD": ticks, "USD_JPY": jpy})
    assert spot.price_at("EUR_USD", NOW) == Decimal("1.1001")
    assert spot.conversion_rate_at("EUR", "USD", NOW) == Decimal("1.1001")
    assert spot.conversion_rate_at("JPY", "USD", NOW) == Decimal("1") / Decimal("150.01")
    assert spot.correlation_candles("EUR_USD", "H1", NOW, 40)

    report = replay_production_portfolio_risk(
        (_execution(),),
        spot_history=spot,
        config=HistoricalPortfolioRiskConfig(
            starting_balance=Decimal("100000"),
            max_units=1_000_000,
            max_gross_exposure_fraction=Decimal("10"),
            max_currency_exposure_fraction=Decimal("10"),
            max_macro_factor_exposure_fraction=Decimal("10"),
        ),
    )
    assert report.admitted_trades == 1
    assert report.denied_trades == 0


def test_normalized_macro_and_flow_files_preserve_real_source_boundaries(tmp_path: Path) -> None:
    calendar_path = tmp_path / "calendar.json"
    calendar_path.write_text(
        json.dumps(
            {
                "metadata": [{"indicator": "CPI", "currency": "USD", "directionality": "1"}],
                "consensus": [
                    {
                        "indicator": "CPI",
                        "currency": "USD",
                        "consensus": "2.7",
                        "previous_known": "2.6",
                        "available_at": "2026-02-03T13:00:00Z",
                        "source": "licensed_calendar",
                    }
                ],
                "actuals": [
                    {
                        "indicator": "CPI",
                        "currency": "USD",
                        "actual": "2.8",
                        "revised_previous": "2.6",
                        "available_at": "2026-02-03T13:30:00Z",
                        "source": "official_actual",
                    }
                ],
            }
        )
    )
    book, macro_meta = _macro_book(
        calendar_path,
        history_start=NOW - timedelta(days=1),
        end=NOW + timedelta(days=1),
    )
    assert book is not None
    assert macro_meta["status"] == "available"
    assert macro_meta["records"] == 1

    flow_path = tmp_path / "flow.json"
    flow_path.write_text(
        json.dumps(
            {
                "order_flow": [
                    {
                        "instrument": "EUR_USD",
                        "observed_at": "2026-02-03T13:59:55Z",
                        "source": "broker_tick_proxy",
                        "delta": "100",
                        "confidence": "1",
                    }
                ]
            }
        )
    )
    flow, flow_meta = _flow_history(flow_path)
    assert flow is None
    assert flow_meta["status"] == "unavailable"
    assert flow_meta["centralized_snapshots"] == 0
