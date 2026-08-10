from __future__ import annotations

from datetime import datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo


NEW_YORK = ZoneInfo("America/New_York")
FX_DAY_CLOSE = time(17, 0)


def fx_risk_day_bounds(instant: datetime) -> tuple[datetime, datetime]:
    """Return the 5 p.m. New York trading-day interval containing *instant*.

    OANDA's FX operating/financing day closes at 5 p.m. New York time. Localizing the
    boundary before converting to UTC makes DST transitions explicit rather than assuming
    a fixed UTC rollover hour.
    """
    if instant.tzinfo is None:
        raise ValueError("risk-day timestamp must be timezone-aware")
    local = instant.astimezone(NEW_YORK)
    start_date = local.date()
    if local.timetz().replace(tzinfo=None) < FX_DAY_CLOSE:
        start_date -= timedelta(days=1)
    start_local = datetime.combine(start_date, FX_DAY_CLOSE, tzinfo=NEW_YORK)
    end_local = datetime.combine(start_date + timedelta(days=1), FX_DAY_CLOSE, tzinfo=NEW_YORK)
    return start_local.astimezone(timezone.utc), end_local.astimezone(timezone.utc)


def fx_risk_day_key(instant: datetime) -> str:
    """Stable key for persistent daily risk state, labeled by New York start date."""
    start, _ = fx_risk_day_bounds(instant)
    return start.astimezone(NEW_YORK).date().isoformat()


def fx_bar_risk_day_key(bar_start: datetime, duration: timedelta) -> str:
    """Risk-day key for price action contained in one completed bar.

    Candle timestamps denote bar starts. A bar ending exactly at the 5 p.m. New York
    boundary belongs to the day that *just closed*, so classification uses the final
    representable instant inside the bar rather than its completion timestamp.
    """
    if bar_start.tzinfo is None:
        raise ValueError("bar start must be timezone-aware")
    if duration <= timedelta(0):
        raise ValueError("bar duration must be positive")
    return fx_risk_day_key(bar_start + duration - timedelta(microseconds=1))


def fx_week_key(instant: datetime) -> str:
    """Return the Sunday-5-p.m.-New-York FX trading-week start date.

    The risk-day start date is used as the atomic trading-day label. Sunday is day zero
    for the FX week; Monday through Friday evening risk days remain in the same week.
    This avoids ISO-calendar behavior that would assign Sunday-evening FX trading to the
    week that is ending rather than the trading week that is beginning.
    """
    if instant.tzinfo is None:
        raise ValueError("FX-week timestamp must be timezone-aware")
    day_start, _ = fx_risk_day_bounds(instant)
    start_date = day_start.astimezone(NEW_YORK).date()
    # Python weekday: Monday=0 .. Sunday=6. Convert to days since Sunday.
    days_since_sunday = (start_date.weekday() + 1) % 7
    week_start = start_date - timedelta(days=days_since_sunday)
    return week_start.isoformat()


def fx_bar_week_key(bar_start: datetime, duration: timedelta) -> str:
    """FX-week key for the price action inside a completed bar."""
    if bar_start.tzinfo is None:
        raise ValueError("bar start must be timezone-aware")
    if duration <= timedelta(0):
        raise ValueError("bar duration must be positive")
    return fx_week_key(bar_start + duration - timedelta(microseconds=1))
