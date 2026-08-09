from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta
from decimal import Decimal
from typing import Iterable

from forex_trader.research.tick_backtest import (
    DailyReturnReport,
    TickBacktestOpportunity,
    simulate_daily_returns,
)


@dataclass(frozen=True, slots=True)
class PeriodReturnReport:
    """Return metrics that distinguish active exit-days from the full test period."""

    active_days: DailyReturnReport
    period_weekdays: int
    average_period_weekday_return: Decimal


def _weekday_count(start: date, end: date) -> int:
    """Count Monday-Friday dates in the half-open interval [start, end)."""
    if end <= start:
        raise ValueError("period end must be after period start")
    days = (end - start).days
    return sum((start + timedelta(days=offset)).weekday() < 5 for offset in range(days))


def simulate_period_returns(
    opportunities: Iterable[TickBacktestOpportunity],
    *,
    period_start: datetime,
    period_end: datetime,
    risk_fraction_per_trade: Decimal = Decimal("0.0015"),
    timezone_name: str = "America/New_York",
) -> PeriodReturnReport:
    """Report strategy return across every weekday in a declared test interval.

    ``simulate_daily_returns`` intentionally summarizes only dates containing selected
    exits. This wrapper preserves that active-day report while also averaging those daily
    returns across every Monday-Friday date in the declared backtest period, assigning
    zero return to weekdays with no selected exits.
    """
    if period_start.tzinfo is None or period_end.tzinfo is None:
        raise ValueError("period boundaries must be timezone-aware")
    if period_end <= period_start:
        raise ValueError("period_end must be after period_start")

    active = simulate_daily_returns(
        tuple(opportunities),
        risk_fraction_per_trade=risk_fraction_per_trade,
        timezone_name=timezone_name,
    )
    weekdays = _weekday_count(period_start.date(), period_end.date())
    if weekdays <= 0:
        raise ValueError("declared period contains no weekdays")
    active_return_sum = active.average_daily_return * Decimal(active.trading_days)
    return PeriodReturnReport(
        active_days=active,
        period_weekdays=weekdays,
        average_period_weekday_return=active_return_sum / Decimal(weekdays),
    )
