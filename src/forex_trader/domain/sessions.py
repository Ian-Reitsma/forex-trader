from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, time, timedelta, timezone
from enum import StrEnum
from zoneinfo import ZoneInfo


class TradingSession(StrEnum):
    ASIA = "asia"
    LONDON = "london"
    NEW_YORK = "new_york"
    LONDON_NEW_YORK_OVERLAP = "london_new_york_overlap"
    OFF_HOURS = "off_hours"


@dataclass(frozen=True, slots=True)
class SessionDefinition:
    session: TradingSession
    timezone_name: str
    local_open: time
    local_close: time

    @property
    def zone(self) -> ZoneInfo:
        return ZoneInfo(self.timezone_name)


TOKYO = SessionDefinition(TradingSession.ASIA, "Asia/Tokyo", time(9, 0), time(18, 0))
LONDON = SessionDefinition(TradingSession.LONDON, "Europe/London", time(8, 0), time(17, 0))
NEW_YORK = SessionDefinition(TradingSession.NEW_YORK, "America/New_York", time(8, 0), time(17, 0))


def _aware_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        raise ValueError("session timestamps must be timezone-aware")
    return value.astimezone(timezone.utc)


def _is_open(value: datetime, definition: SessionDefinition) -> bool:
    local = _aware_utc(value).astimezone(definition.zone)
    current = local.timetz().replace(tzinfo=None)
    return definition.local_open <= current < definition.local_close


def classify_session(value: datetime) -> TradingSession:
    """Classify a timestamp using local market clocks, including DST transitions."""
    london = _is_open(value, LONDON)
    new_york = _is_open(value, NEW_YORK)
    if london and new_york:
        return TradingSession.LONDON_NEW_YORK_OVERLAP
    if london:
        return TradingSession.LONDON
    if new_york:
        return TradingSession.NEW_YORK
    if _is_open(value, TOKYO):
        return TradingSession.ASIA
    return TradingSession.OFF_HOURS


def session_bounds_utc(value: datetime, definition: SessionDefinition) -> tuple[datetime, datetime]:
    """Return the local-session open/close containing, or most recently preceding, *value*."""
    instant = _aware_utc(value)
    local = instant.astimezone(definition.zone)
    session_date = local.date()
    if local.timetz().replace(tzinfo=None) < definition.local_open:
        session_date -= timedelta(days=1)
    start_local = datetime.combine(session_date, definition.local_open, tzinfo=definition.zone)
    end_local = datetime.combine(session_date, definition.local_close, tzinfo=definition.zone)
    return start_local.astimezone(timezone.utc), end_local.astimezone(timezone.utc)
