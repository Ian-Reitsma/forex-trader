from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from forex_trader.domain.macro_history import MacroObservation, PointInTimeFundamentalBook
from forex_trader.infrastructure.trading_repository import TradingRepository


NOW = datetime(2026, 8, 10, 3, 0, tzinfo=UTC)


def test_release_can_be_first_seen_after_event_without_becoming_artificially_fresh(tmp_path) -> None:
    event_at = NOW - timedelta(days=6)
    observation = MacroObservation.release(
        currency="USD",
        category="inflation",
        actual=Decimal("3.0"),
        forecast=Decimal("2.8"),
        previous=Decimal("2.7"),
        higher_is_positive=False,
        available_at=NOW,
        event_at=event_at,
        source="trading_economics:event-1",
    )
    repository = TradingRepository(tmp_path / "macro.db")
    repository.save_macro_observation(observation)
    loaded = repository.macro_observations()[0]
    assert loaded.available_at == NOW
    assert loaded.event_at == event_at

    book = PointInTimeFundamentalBook([loaded])
    assert book.observations(as_of=NOW - timedelta(seconds=1)) == []
    assessment = book.get("USD", as_of=NOW)
    assert assessment is not None
    assert assessment.as_of == event_at

    pair = book.assess_pair("USD_EUR", as_of=NOW)
    assert pair.confidence == Decimal("0")
    assert any("missing fundamental state for EUR" in reason for reason in pair.reasons)


def test_event_timestamp_validation_is_fail_closed() -> None:
    with pytest.raises(ValueError, match="event_at must be timezone-aware"):
        MacroObservation.release(
            currency="USD",
            category="growth",
            actual=Decimal("1"),
            forecast=Decimal("1"),
            previous=Decimal("1"),
            higher_is_positive=True,
            available_at=NOW,
            event_at=datetime(2026, 8, 9),
        )
    with pytest.raises(ValueError, match="after available_at"):
        MacroObservation.release(
            currency="USD",
            category="growth",
            actual=Decimal("1"),
            forecast=Decimal("1"),
            previous=Decimal("1"),
            higher_is_positive=True,
            available_at=NOW,
            event_at=NOW + timedelta(seconds=1),
        )
