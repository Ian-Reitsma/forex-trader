from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

from forex_trader.application.practice_execution_guard import assess_practice_execution_gate
from forex_trader.research.capital_utilization import (
    analyze_trace_capital_utilization,
    summarize_capital_utilization,
)


def _trace(*, units: int = 100000, risk_amount: str = "75") -> dict[str, object]:
    return {
        "trace_id": "trace-1",
        "instrument": "EUR_USD",
        "candidate": {"entry_price": "1.1000"},
        "risk": {"disposition": "granted", "units": units, "risk_amount": risk_amount},
        "metadata": {
            "account_snapshot": {"balance": "100000", "nav": "100000"},
            "instrument_spec": {
                "maximum_position_size": "1000000",
                "margin_rate": "0.02",
            },
        },
    }


def test_capital_utilization_detects_configured_unit_cap() -> None:
    observation = analyze_trace_capital_utilization(
        _trace(),
        risk_fraction=Decimal("0.0015"),
        configured_max_units=100000,
    )
    assert observation is not None
    assert observation.risk_budget == Decimal("150.0000")
    assert observation.risk_utilization_fraction == Decimal("0.5")
    assert observation.raw_risk_budget_units == 200000
    assert observation.binding_limit == "configured_max_units"
    assert observation.quote_currency_notional == Decimal("110000.0000")
    assert observation.quote_currency_estimated_margin == Decimal("2200.000000")


def test_capital_utilization_reports_full_budget_when_not_capped() -> None:
    observation = analyze_trace_capital_utilization(
        _trace(units=150000, risk_amount="150"),
        risk_fraction=Decimal("0.0015"),
        configured_max_units=500000,
    )
    assert observation is not None
    assert observation.risk_utilization_fraction == Decimal("1")
    assert observation.binding_limit is None


def test_capital_utilization_summary_counts_underutilization() -> None:
    report = summarize_capital_utilization(
        [_trace(), _trace(units=100000, risk_amount="150")],
        risk_fraction=Decimal("0.0015"),
        configured_max_units=100000,
    )
    assert report["observations"] == 2
    assert report["under_90_percent_risk_budget_count"] == 1
    assert report["binding_limit_count"] == 1


def test_execution_review_assessment_flags_three_losses(engine, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.setattr(
        engine.repository,
        "advanced_risk_state",
        lambda account_id, nav: {"loss_streak": 3},
        raising=False,
    )
    monkeypatch.setattr(
        engine,
        "promotion_status",
        lambda: {
            "ready": False,
            "metrics": {"closed_trades": 9, "wins": 0, "total_pl": "-633.0883"},
        },
    )
    status = assess_practice_execution_gate(engine, review_loss_streak_limit=3)
    assert status.review_recommended is True
    assert status.loss_streak == 3
    assert status.promotion_closed_trades == 9
    assert status.promotion_wins == 0
    assert status.promotion_total_pl == "-633.0883"
    assert status.observed_at <= datetime.now(UTC)
    assert status.to_jsonable()["broker_write_authority"] is False
