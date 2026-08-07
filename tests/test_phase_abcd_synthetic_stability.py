from __future__ import annotations

from datetime import UTC, datetime

from forex_trader.adapters.synthetic import _stable_future_anchor


def test_synthetic_anchor_is_session_stable_across_hour_boundary() -> None:
    before = _stable_future_anchor(datetime(2026, 8, 6, 18, 59, tzinfo=UTC))
    after = _stable_future_anchor(datetime(2026, 8, 6, 19, 1, tzinfo=UTC))
    friday_after = _stable_future_anchor(datetime(2026, 8, 7, 19, 1, tzinfo=UTC))

    assert before == datetime(2026, 8, 6, 19, 0, tzinfo=UTC)
    assert after == datetime(2026, 8, 7, 19, 0, tzinfo=UTC)
    assert friday_after == datetime(2026, 8, 10, 19, 0, tzinfo=UTC)
    assert all(anchor.hour == 19 and anchor.weekday() < 5 for anchor in (before, after, friday_after))
