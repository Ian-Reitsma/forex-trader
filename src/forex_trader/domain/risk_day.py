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
