from datetime import datetime, timezone

import pytest

from forex_trader.domain.sessions import LONDON, NEW_YORK, TradingSession, classify_session, session_bounds_utc


def dt(month: int, day: int, hour: int) -> datetime:
    return datetime(2026, month, day, hour, tzinfo=timezone.utc)


def test_london_session_moves_with_dst() -> None:
    winter_start, _ = session_bounds_utc(dt(1, 15, 12), LONDON)
    summer_start, _ = session_bounds_utc(dt(7, 15, 12), LONDON)
    assert winter_start.hour == 8
    assert summer_start.hour == 7


def test_new_york_session_moves_with_dst() -> None:
    winter_start, _ = session_bounds_utc(dt(1, 15, 15), NEW_YORK)
    summer_start, _ = session_bounds_utc(dt(7, 15, 15), NEW_YORK)
    assert winter_start.hour == 13
    assert summer_start.hour == 12


def test_overlap_is_classified_from_local_clocks() -> None:
    assert classify_session(dt(7, 15, 13)) == TradingSession.LONDON_NEW_YORK_OVERLAP


def test_naive_timestamps_are_rejected() -> None:
    with pytest.raises(ValueError):
        classify_session(datetime(2026, 1, 1, 12))
