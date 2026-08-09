from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from decimal import Decimal
from typing import Iterable
from zoneinfo import ZoneInfo

from forex_trader.domain.risk_day import FX_DAY_CLOSE, NEW_YORK, fx_risk_day_key
from forex_trader.research.tick_backtest import (
    DailyReturnReport,
    TickBacktestOpportunity,
    simulate_daily_returns,
)


@dataclass(frozen=True, slots=True)
class PeriodReturnReport:
    """Return metrics across both legacy calendar dates and canonical FX risk days.

    ``active_days`` / ``period_weekdays`` are retained for backward-compatible
    diagnostics. New research should use ``active_fx_risk_days`` and
    ``average_period_fx_risk_day_return`` because runtime daily risk is keyed to the
    5 p.m. New York FX boundary rather than midnight calendar dates.
    """

    active_days: DailyReturnReport
    period_weekdays: int
    average_period_weekday_return: Decimal
    active_fx_risk_days: DailyReturnReport
    period_fx_risk_days: int
    average_period_fx_risk_day_return: Decimal
    day_basis: str = "5pm_America/New_York_fx_risk_day"


def _weekday_count(start: date, end: date) -> int:
    """Count Monday-Friday dates in the half-open interval [start, end)."""
    if end <= start:
        raise ValueError("period end must be after period start")
    days = (end - start).days
    return sum((start + timedelta(days=offset)).weekday() < 5 for offset in range(days))


def _fx_risk_day_count(period_start: datetime, period_end: datetime) -> int:
    """Count FX risk-day intervals that overlap a declared test interval.

    A normal FX week has five sessions beginning Sunday through Thursday at 5 p.m.
    New York. Counting intersecting risk-day intervals keeps partial boundary sessions
    explicit and uses the same DST-aware boundary as runtime risk state.
    """
    local_start = period_start.astimezone(NEW_YORK).date() - timedelta(days=1)
    local_end = period_end.astimezone(NEW_YORK).date() + timedelta(days=1)
    current = local_start
    count = 0
    while current <= local_end:
        if current.weekday() in {6, 0, 1, 2, 3}:  # Sunday through Thursday.
            start_local = datetime.combine(current, FX_DAY_CLOSE, tzinfo=NEW_YORK)
            end_local = datetime.combine(current + timedelta(days=1), FX_DAY_CLOSE, tzinfo=NEW_YORK)
            if start_local < period_end.astimezone(NEW_YORK) and end_local > period_start.astimezone(NEW_YORK):
                count += 1
        current += timedelta(days=1)
    return count


def _simulate_fx_risk_day_returns(
    opportunities: Iterable[TickBacktestOpportunity],
    *,
    risk_fraction_per_trade: Decimal,
) -> DailyReturnReport:
    if not Decimal("0") < risk_fraction_per_trade <= Decimal("0.05"):
        raise ValueError("risk_fraction_per_trade must be in (0,0.05]")
    equity = Decimal("1")
    peak = equity
    maximum_drawdown = Decimal("0")
    starts: dict[str, Decimal] = {}
    ends: dict[str, Decimal] = {}
    for opportunity in sorted(opportunities, key=lambda item: (item.exit_time, item.instrument)):
        day = fx_risk_day_key(opportunity.exit_time)
        starts.setdefault(day, equity)
        equity *= Decimal("1") + risk_fraction_per_trade * opportunity.trade.r_multiple
        ends[day] = equity
        peak = max(peak, equity)
        maximum_drawdown = max(maximum_drawdown, (peak - equity) / peak)
    if not ends:
        return DailyReturnReport(
            risk_fraction_per_trade=risk_fraction_per_trade,
            total_return=Decimal("0"),
            average_daily_return=Decimal("0"),
            median_daily_return=Decimal("0"),
            best_daily_return=Decimal("0"),
            worst_daily_return=Decimal("0"),
            profitable_day_fraction=Decimal("0"),
            trading_days=0,
            maximum_equity_drawdown=Decimal("0"),
        )
    returns = sorted(ends[day] / starts[day] - Decimal("1") for day in ends)
    midpoint = len(returns) // 2
    median = returns[midpoint] if len(returns) % 2 else (returns[midpoint - 1] + returns[midpoint]) / Decimal("2")
    return DailyReturnReport(
        risk_fraction_per_trade=risk_fraction_per_trade,
        total_return=equity - Decimal("1"),
        average_daily_return=sum(returns, Decimal("0")) / Decimal(len(returns)),
        median_daily_return=median,
        best_daily_return=max(returns),
        worst_daily_return=min(returns),
        profitable_day_fraction=Decimal(sum(value > 0 for value in returns)) / Decimal(len(returns)),
        trading_days=len(returns),
        maximum_equity_drawdown=maximum_drawdown,
    )


def simulate_period_returns(
    opportunities: Iterable[TickBacktestOpportunity],
    *,
    period_start: datetime,
    period_end: datetime,
    risk_fraction_per_trade: Decimal = Decimal("0.0015"),
    timezone_name: str = "America/New_York",
) -> PeriodReturnReport:
    """Report returns across a declared interval without conflating calendar and FX days.

    The legacy calendar-exit-day metrics remain available because older evidence artifacts
    used them. The canonical research metric now groups exits by ``fx_risk_day_key`` and
    averages over every 5 p.m. New York FX risk-day interval intersecting the test period.
    """
    if period_start.tzinfo is None or period_end.tzinfo is None:
        raise ValueError("period boundaries must be timezone-aware")
    if period_end <= period_start:
        raise ValueError("period_end must be after period_start")
    # Validate the legacy timezone argument exactly as before; it remains part of the
    # backward-compatible calendar-date diagnostics.
    ZoneInfo(timezone_name)
    values = tuple(opportunities)
    active = simulate_daily_returns(
        values,
        risk_fraction_per_trade=risk_fraction_per_trade,
        timezone_name=timezone_name,
    )
    weekdays = _weekday_count(period_start.date(), period_end.date())
    if weekdays <= 0:
        raise ValueError("declared period contains no weekdays")
    legacy_active_return_sum = active.average_daily_return * Decimal(active.trading_days)

    active_fx = _simulate_fx_risk_day_returns(values, risk_fraction_per_trade=risk_fraction_per_trade)
    fx_days = _fx_risk_day_count(period_start, period_end)
    if fx_days <= 0:
        raise ValueError("declared period contains no FX risk days")
    fx_active_return_sum = active_fx.average_daily_return * Decimal(active_fx.trading_days)
    return PeriodReturnReport(
        active_days=active,
        period_weekdays=weekdays,
        average_period_weekday_return=legacy_active_return_sum / Decimal(weekdays),
        active_fx_risk_days=active_fx,
        period_fx_risk_days=fx_days,
        average_period_fx_risk_day_return=fx_active_return_sum / Decimal(fx_days),
    )
