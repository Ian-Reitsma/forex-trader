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
    # Backward-compatible alias used by pre-v0.5 cost fixtures.
    LONDON_NEW_YORK = "london_new_york_overlap"
    OFF_HOURS = "off_hours"


class SessionPhase(StrEnum):
    ASIA = "asia"
    PRE_LONDON = "pre_london"
    LONDON_OPEN = "london_open"
    LONDON_CONTINUATION = "london_continuation"
    PRE_NEW_YORK = "pre_new_york"
    LONDON_NEW_YORK_OVERLAP = "london_new_york_overlap"
    NEW_YORK_OPEN = "new_york_open"
    NEW_YORK_CONTINUATION = "new_york_continuation"
    LONDON_FIX = "london_fix"
    ROLLOVER = "rollover"
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
    """Classify using local market clocks, including UK/US DST mismatch weeks."""
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


def classify_phase(value: datetime) -> SessionPhase:
    """Provide finer strategy phases without reverting to fixed UTC offsets."""
    instant = _aware_utc(value)
    london = instant.astimezone(ZoneInfo("Europe/London"))
    new_york = instant.astimezone(ZoneInfo("America/New_York"))
    tokyo = instant.astimezone(ZoneInfo("Asia/Tokyo"))
    london_time = london.timetz().replace(tzinfo=None)
    ny_time = new_york.timetz().replace(tzinfo=None)
    tokyo_time = tokyo.timetz().replace(tzinfo=None)

    # The 17:00 New York rollover is an execution-quality blackout by default.
    if time(16, 45) <= ny_time < time(17, 15):
        return SessionPhase.ROLLOVER
    if time(15, 50) <= london_time < time(16, 10):
        return SessionPhase.LONDON_FIX
    if time(7, 0) <= london_time < time(8, 0):
        return SessionPhase.PRE_LONDON
    if time(8, 0) <= london_time < time(9, 30):
        return SessionPhase.LONDON_OPEN
    if time(9, 30) <= london_time < time(12, 0):
        return SessionPhase.LONDON_CONTINUATION
    if time(7, 0) <= ny_time < time(8, 0):
        return SessionPhase.PRE_NEW_YORK
    if _is_open(instant, LONDON) and _is_open(instant, NEW_YORK):
        if time(8, 0) <= ny_time < time(10, 0):
            return SessionPhase.NEW_YORK_OPEN
        return SessionPhase.LONDON_NEW_YORK_OVERLAP
    if time(10, 0) <= ny_time < time(16, 0):
        return SessionPhase.NEW_YORK_CONTINUATION
    if time(9, 0) <= tokyo_time < time(18, 0):
        return SessionPhase.ASIA
    return SessionPhase.OFF_HOURS


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
