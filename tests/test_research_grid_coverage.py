from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

from forex_trader.domain.macro_history import MacroObservation
from forex_trader.research.adaptive_managed_strategy import (
    compact_strategy_filter_grid,
    default_shadow_gate_grid,
)
from forex_trader.research.managed_tick_backtest import _latest_news_age_minutes
from forex_trader.research.tick_backtest import SessionFilter


NOW = datetime(2026, 7, 20, 12, tzinfo=UTC)


def test_adaptive_default_grids_are_complete_and_bounded() -> None:
    filters = compact_strategy_filter_grid()
    gates = default_shadow_gate_grid()

    assert len(filters) == 180
    assert {item.session_filter for item in filters} == {
        SessionFilter.LIQUID,
        SessionFilter.OPEN_ONLY,
    }
    assert {item.minimum_score for item in filters} == {
        Decimal("0.45"),
        Decimal("0.50"),
        Decimal("0.55"),
        Decimal("0.60"),
        Decimal("0.65"),
    }
    assert {item.maximum_spread_pips for item in filters} == {
        Decimal("0.6"),
        Decimal("0.8"),
        Decimal("1.2"),
    }

    assert len(gates) == 27
    assert {item.lookback for item in gates} == {6, 10, 16}
    assert {item.minimum_samples for item in gates} == {4, 6, 8}
    assert {item.minimum_economic_win_rate for item in gates} == {
        Decimal("0.50"),
        Decimal("0.60"),
        Decimal("0.70"),
    }
    assert {item.minimum_expectancy_r for item in gates} == {
        Decimal("-0.05"),
        Decimal("0"),
        Decimal("0.05"),
    }
    assert all("lookback=" in item.identity for item in gates)


def test_managed_news_age_is_pair_scoped_and_point_in_time() -> None:
    observations = (
        MacroObservation.news(
            currency="EUR",
            headline="ECB update",
            available_at=NOW - timedelta(minutes=45),
        ),
        MacroObservation.news(
            currency="JPY",
            headline="BoJ update",
            available_at=NOW - timedelta(minutes=20),
        ),
        MacroObservation.news(
            currency="USD",
            headline="Fed update",
            available_at=NOW - timedelta(minutes=10),
        ),
        MacroObservation.news(
            currency="EUR",
            headline="future ECB update",
            available_at=NOW + timedelta(minutes=5),
        ),
    )
    ordered = tuple(sorted(observations, key=lambda item: item.available_at))

    assert _latest_news_age_minutes(
        ordered,
        currencies=("EUR", "USD"),
        as_of=NOW,
    ) == Decimal("10")
    assert _latest_news_age_minutes(
        ordered,
        currencies=("GBP", "CHF"),
        as_of=NOW,
    ) is None
