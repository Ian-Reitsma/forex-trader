from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from forex_trader.domain.enums import Direction
from forex_trader.domain.sessions import SessionPhase
from forex_trader.research.backtest import BacktestTrade, OutcomeStatus
from forex_trader.research.return_reporting import simulate_period_returns
from forex_trader.research.tick_backtest import TickBacktestOpportunity


def _opportunity(instant: datetime, r_multiple: str) -> TickBacktestOpportunity:
    realized = Decimal(r_multiple)
    return TickBacktestOpportunity(
        instrument="EUR_USD",
        decision_time=instant,
        entry_time=instant + timedelta(seconds=1),
        exit_time=instant + timedelta(minutes=5),
        trade=BacktestTrade(
            instrument="EUR_USD",
            direction=Direction.LONG,
            signal_time=instant,
            score=Decimal("0.70"),
            status=OutcomeStatus.WIN if realized > 0 else OutcomeStatus.LOSS,
            r_multiple=realized,
            bars_held=1,
        ),
        technical_score=Decimal("0.70"),
        reward_risk=Decimal("1.50"),
        spread_pips=Decimal("0.50"),
        displacement=True,
        session_phase=SessionPhase.NEW_YORK_OPEN,
        news_directional=Decimal("0"),
        news_confidence=Decimal("0"),
        latest_news_age_minutes=None,
        setup_family="sweep_reclaim",
    )


def test_period_return_includes_zero_trade_days_on_both_bases() -> None:
    start = datetime(2026, 8, 3, tzinfo=UTC)  # Monday 00:00 UTC
    end = datetime(2026, 8, 10, tzinfo=UTC)  # next Monday 00:00 UTC
    values = (
        _opportunity(start + timedelta(hours=14), "1.0"),
        _opportunity(start + timedelta(days=1, hours=14), "-0.5"),
    )
    report = simulate_period_returns(
        values,
        period_start=start,
        period_end=end,
        risk_fraction_per_trade=Decimal("0.01"),
    )
    assert report.period_weekdays == 5
    assert report.active_days.trading_days == 2
    assert report.active_days.average_daily_return == Decimal("0.0025")
    assert report.average_period_weekday_return == Decimal("0.001")

    # UTC midnight boundaries cut through the Sunday-start FX sessions at both
    # ends of this interval, so six 5 p.m.-New-York risk-day intervals overlap it.
    assert report.period_fx_risk_days == 6
    assert report.active_fx_risk_days.trading_days == 2
    assert report.active_fx_risk_days.average_daily_return == Decimal("0.0025")
    assert report.average_period_fx_risk_day_return == Decimal("0.005") / Decimal("6")
    assert report.day_basis == "5pm_America/New_York_fx_risk_day"


def test_sunday_evening_and_monday_daytime_share_one_fx_risk_day() -> None:
    # Use exact Sunday-5-p.m.-NY through Friday-5-p.m.-NY boundaries so this is a
    # complete five-session FX week rather than a UTC-midnight partial-session window.
    start = datetime(2026, 8, 2, 21, 0, tzinfo=UTC)
    end = datetime(2026, 8, 7, 21, 0, tzinfo=UTC)
    # Sunday 6 p.m. New York and Monday 10 a.m. New York are the same FX risk day
    # (Sunday 5 p.m. -> Monday 5 p.m.), despite being different calendar exit dates.
    sunday_evening = datetime(2026, 8, 2, 22, 0, tzinfo=UTC)
    monday_daytime = datetime(2026, 8, 3, 14, 0, tzinfo=UTC)
    values = (_opportunity(sunday_evening, "1"), _opportunity(monday_daytime, "1"))
    report = simulate_period_returns(
        values,
        period_start=start,
        period_end=end,
        risk_fraction_per_trade=Decimal("0.01"),
    )
    assert report.period_fx_risk_days == 5
    assert report.active_days.trading_days == 2
    assert report.active_fx_risk_days.trading_days == 1
    assert report.active_fx_risk_days.total_return == Decimal("0.0201")
    assert report.average_period_fx_risk_day_return == Decimal("0.0201") / Decimal("5")


def test_partial_period_counts_intersecting_fx_risk_days() -> None:
    start = datetime(2026, 1, 5, tzinfo=UTC)
    end = datetime(2026, 4, 1, tzinfo=UTC)
    report = simulate_period_returns((), period_start=start, period_end=end)
    # The UTC boundaries cut through the Sunday-Jan-4 and Tuesday-Mar-31 FX days,
    # so 63 canonical 5 p.m. New York risk-day intervals intersect the test window.
    assert report.period_weekdays == 62
    assert report.period_fx_risk_days == 63


def test_empty_period_has_zero_return_but_preserves_period_denominators() -> None:
    start = datetime(2026, 8, 3, tzinfo=UTC)
    end = datetime(2026, 8, 10, tzinfo=UTC)
    report = simulate_period_returns((), period_start=start, period_end=end)
    assert report.period_weekdays == 5
    assert report.active_days.trading_days == 0
    assert report.average_period_weekday_return == 0
    assert report.period_fx_risk_days == 6
    assert report.active_fx_risk_days.trading_days == 0
    assert report.average_period_fx_risk_day_return == 0


def test_period_boundaries_must_be_ordered_and_timezone_aware() -> None:
    aware = datetime(2026, 8, 3, tzinfo=UTC)
    naive = datetime(2026, 8, 3)
    with pytest.raises(ValueError, match="timezone-aware"):
        simulate_period_returns((), period_start=naive, period_end=aware + timedelta(days=1))
    with pytest.raises(ValueError, match="after period_start"):
        simulate_period_returns((), period_start=aware, period_end=aware)
