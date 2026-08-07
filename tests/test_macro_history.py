from datetime import UTC, datetime, timedelta
from decimal import Decimal

from forex_trader.domain.macro_history import MacroObservation, PointInTimeFundamentalBook
from forex_trader.domain.models import CurrencyFundamentals


def test_point_in_time_fundamentals_never_see_future_observations() -> None:
    start = datetime(2026, 1, 1, tzinfo=UTC)
    seeds = [
        CurrencyFundamentals("EUR", confidence=Decimal("0.8"), as_of=start),
        CurrencyFundamentals("USD", confidence=Decimal("0.8"), as_of=start),
    ]
    first = MacroObservation.release(
        currency="EUR",
        category="growth",
        actual=Decimal("110"),
        forecast=Decimal("100"),
        previous=Decimal("100"),
        higher_is_positive=True,
        available_at=start + timedelta(hours=1),
    )
    future = MacroObservation.release(
        currency="USD",
        category="labor",
        actual=Decimal("300"),
        forecast=Decimal("100"),
        previous=Decimal("100"),
        higher_is_positive=True,
        available_at=start + timedelta(hours=3),
    )
    history = PointInTimeFundamentalBook([future, first], seeds=seeds)
    before_future = history.assess_pair("EUR_USD", as_of=start + timedelta(hours=2))
    after_future = history.assess_pair("EUR_USD", as_of=start + timedelta(hours=4))
    assert before_future.differential > 0
    assert after_future.differential < before_future.differential
    assert history.observations(as_of=start + timedelta(hours=2)) == [first]


def test_macro_release_requires_values() -> None:
    from forex_trader.domain.macro_history import MacroObservationKind
    import pytest

    with pytest.raises(ValueError, match="require actual"):
        MacroObservation(
            observation_id=__import__("uuid").uuid4(),
            kind=MacroObservationKind.RELEASE,
            currency="USD",
            available_at=datetime.now(UTC),
        )


def test_future_seed_is_not_visible_before_its_timestamp() -> None:
    start = datetime(2026, 1, 1, tzinfo=UTC)
    future_seed = CurrencyFundamentals(
        "EUR",
        growth=Decimal("1"),
        confidence=Decimal("1"),
        as_of=start + timedelta(days=1),
    )
    history = PointInTimeFundamentalBook(seeds=[future_seed])
    book = history.book_at(start)
    assert book.snapshots() == []
