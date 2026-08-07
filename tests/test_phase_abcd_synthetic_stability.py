from __future__ import annotations

from datetime import UTC, datetime

from forex_trader.adapters.synthetic import DEFAULT_SYNTHETIC_ANCHOR, SyntheticMarketData


def test_synthetic_default_clock_is_fixed_session_stable_and_weekday() -> None:
    first = SyntheticMarketData(seed=1)
    second = SyntheticMarketData(seed=2)

    assert first.anchor == DEFAULT_SYNTHETIC_ANCHOR
    assert second.anchor == DEFAULT_SYNTHETIC_ANCHOR
    assert DEFAULT_SYNTHETIC_ANCHOR == datetime(2025, 1, 15, 19, 0, tzinfo=UTC)
    assert DEFAULT_SYNTHETIC_ANCHOR.hour == 19
    assert DEFAULT_SYNTHETIC_ANCHOR.weekday() < 5
