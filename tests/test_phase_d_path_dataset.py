from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import uuid4

import pytest

from forex_trader.domain.models import Candle
from forex_trader.research.evidence import DecisionEvidence
from forex_trader.research.path_dataset import build_phase_d_scenarios, load_candle_archive


BASE = datetime(2026, 1, 5, 14, 0, tzinfo=UTC)


def decision(index: int = 0) -> DecisionEvidence:
    signal = BASE + timedelta(minutes=5 * index)
    return DecisionEvidence(
        campaign_id="campaign-a",
        policy_fingerprint="policy-a",
        cycle=index + 1,
        instrument="EUR_USD",
        trace_id=f"trace-{index}",
        candidate_id=str(uuid4()),
        captured_at=signal,
        signal_time=signal,
        direction="long",
        disposition="trade",
        setup_family="zone_liquidity_sweep_reclaim",
        setup_state="entry_confirmed",
        rejection_code=None,
        score=Decimal("0.75"),
        technical_score=Decimal("0.8"),
        fundamental_score=Decimal("0.6"),
        fundamental_confidence=Decimal("0.8"),
        entry_price=Decimal("1.1000"),
        stop_loss=Decimal("1.0990"),
        take_profit=Decimal("1.1030"),
        quote_bid=Decimal("1.0999"),
        quote_ask=Decimal("1.1000"),
        quote_time=signal,
        regime="trend",
        session_phase="london",
        selected_policy="sweep_reclaim:v1",
        policy_authority="practice",
        confirmation_categories=("price", "fundamental"),
        confirmation_source_ids=("price", "macro"),
        risk_disposition="granted",
        risk_units=1000,
        risk_amount=Decimal("1"),
        order_status=None,
        execution_enabled=False,
        candidate_evidence={},
    )


def candle(index: int) -> Candle:
    return Candle(
        BASE + timedelta(minutes=5 * index),
        Decimal("1.1000"),
        Decimal("1.1005"),
        Decimal("1.0995"),
        Decimal("1.1001"),
    )


def test_candle_archive_rejects_duplicate_instrument_time(tmp_path) -> None:
    path = tmp_path / "candles.jsonl"
    row = {
        "instrument": "EUR_USD",
        "time": BASE.isoformat(),
        "open": "1.1000",
        "high": "1.1010",
        "low": "1.0990",
        "close": "1.1005",
        "complete": True,
    }
    path.write_text(json.dumps(row) + "\n" + json.dumps(row) + "\n", encoding="utf-8")
    with pytest.raises(ValueError, match="duplicate candle archive row"):
        load_candle_archive(path)


def test_build_phase_d_scenarios_requires_complete_combined_horizon() -> None:
    record = decision()
    short = {"EUR_USD": [candle(index) for index in range(1, 5)]}
    assert build_phase_d_scenarios(
        [record],
        candles_by_instrument=short,
        maximum_entry_bars=2,
        maximum_holding_bars=3,
    ) == ()

    complete = {"EUR_USD": [candle(index) for index in range(1, 6)]}
    scenarios = build_phase_d_scenarios(
        [record],
        complete,
        maximum_entry_bars=2,
        maximum_holding_bars=3,
    )
    assert len(scenarios) == 1
    assert len(scenarios[0].future_candles) == 5
    assert scenarios[0].spread_pips == Decimal("1")


def test_build_phase_d_scenarios_respects_as_of_cutoff() -> None:
    record = decision()
    candles = {"EUR_USD": [candle(index) for index in range(1, 8)]}
    scenarios = build_phase_d_scenarios(
        [record],
        candles,
        maximum_entry_bars=2,
        maximum_holding_bars=3,
        as_of=BASE + timedelta(minutes=20),
    )
    assert scenarios == ()
