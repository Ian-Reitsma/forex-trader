from dataclasses import replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from forex_trader.adapters.synthetic import SyntheticMarketData
from forex_trader.domain.costs import SessionCostModel
from forex_trader.domain.events import EventImportance, ScheduledMacroEvent, pair_event_blackout
from forex_trader.domain.instruments import clear_registry, pip_size_for, register_instrument
from forex_trader.domain.macro_history import MacroObservation, PointInTimeFundamentalBook
from forex_trader.domain.models import CurrencyFundamentals
from forex_trader.domain.portfolio import OpenPosition, currency_exposure
from forex_trader.domain.sessions import TradingSession, classify_session
from forex_trader.domain.technicals import assess_technicals
from forex_trader.infrastructure.trading_repository import TradingRepository


def test_broker_metadata_pip_size_overrides_name_heuristic() -> None:
    clear_registry()
    assert pip_size_for("EUR_HUF") == Decimal("0.0001")
    register_instrument("EUR_HUF", pip_size=Decimal("0.01"))
    assert pip_size_for("EUR_HUF") == Decimal("0.01")
    clear_registry()


def test_dst_session_classifier_handles_us_uk_mismatch_weeks() -> None:
    january = datetime(2026, 1, 15, 12, 30, tzinfo=UTC)
    march_mismatch = datetime(2026, 3, 10, 12, 30, tzinfo=UTC)
    assert classify_session(january) is TradingSession.LONDON
    assert classify_session(march_mismatch) is TradingSession.LONDON_NEW_YORK_OVERLAP


def test_slippage_only_samples_contribute_to_cost_profile() -> None:
    model = SessionCostModel(minimum_samples=1)
    sample = model.record_slippage(
        instrument="EUR_USD",
        observed_at=datetime(2026, 3, 10, 13, tzinfo=UTC),
        intended_price=Decimal("1.10000"),
        fill_price=Decimal("1.10005"),
        direction="long",
    )
    assert sample.spread_pips == 0
    profile = model.profile("EUR_USD", sample.observed_at)
    assert profile is not None
    assert profile.spread_sample_count == 0
    assert profile.slippage_sample_count == 1
    assert profile.median_slippage_pips == Decimal("0.5")


def test_signed_slippage_distinguishes_price_improvement() -> None:
    model = SessionCostModel(minimum_samples=1)
    improvement = model.record_slippage(
        instrument="EUR_USD",
        observed_at=datetime(2026, 3, 10, 13, tzinfo=UTC),
        intended_price=Decimal("1.10000"),
        fill_price=Decimal("1.09995"),
        direction="long",
    )
    assert improvement.slippage_pips == Decimal("-0.5")


def test_point_in_time_book_excludes_future_runtime_observations() -> None:
    start = datetime(2026, 1, 1, tzinfo=UTC)
    seed = CurrencyFundamentals("USD", policy=Decimal("0.2"), confidence=Decimal("0.8"), as_of=start)
    future = MacroObservation.news(
        currency="USD",
        headline="dovish rate cut",
        available_at=start + timedelta(hours=2),
        source_weight=Decimal("1"),
    )
    book = PointInTimeFundamentalBook([future], seeds=[seed, CurrencyFundamentals("EUR", as_of=start)])
    before = book.get("USD", as_of=start + timedelta(hours=1))
    after = book.get("USD", as_of=start + timedelta(hours=3))
    assert before is not None and after is not None
    assert before.news == 0
    assert after.news < 0


def test_macro_observations_are_immutable_by_id() -> None:
    repository = TradingRepository(":memory:")
    observation = MacroObservation.news(
        currency="USD",
        headline="first text",
        available_at=datetime(2026, 1, 1, tzinfo=UTC),
    )
    repository.save_macro_observation(observation)
    repository.save_macro_observation(observation)
    with pytest.raises(ValueError, match="immutable"):
        repository.save_macro_observation(replace(observation, headline="rewritten history"))


def test_scheduled_events_round_trip_and_block_pair() -> None:
    repository = TradingRepository(":memory:")
    when = datetime(2026, 8, 7, 13, 30, tzinfo=UTC)
    event = ScheduledMacroEvent.create(
        currency="USD",
        scheduled_at=when,
        name="Payrolls",
        importance=EventImportance.HIGH,
        pre_blackout=timedelta(minutes=20),
        post_blackout=timedelta(minutes=10),
    )
    repository.save_scheduled_event(event)
    loaded = repository.scheduled_events(start=when - timedelta(hours=1), end=when + timedelta(hours=1))
    assert loaded == [event]
    blocked, reasons = pair_event_blackout("EUR_USD", when - timedelta(minutes=5), loaded)
    assert blocked is True
    assert "Payrolls" in reasons[0]


def test_account_execution_lock_is_atomic_and_releasable() -> None:
    repository = TradingRepository(":memory:")
    assert repository.acquire_account_lock("A", "owner-1", ttl_seconds=30) is True
    assert repository.acquire_account_lock("A", "owner-2", ttl_seconds=30) is False
    repository.release_account_lock("A", "owner-1")
    assert repository.acquire_account_lock("A", "owner-2", ttl_seconds=30) is True


def test_daily_loss_latch_does_not_reset_after_recovery() -> None:
    repository = TradingRepository(":memory:")
    assert repository.observe_risk_day(account_id="A", trading_day="2026-08-07", marked_pl=Decimal("-101"), loss_limit_amount=Decimal("100")) is True
    assert repository.observe_risk_day(account_id="A", trading_day="2026-08-07", marked_pl=Decimal("-10"), loss_limit_amount=Decimal("100")) is True


def test_gross_hedged_position_does_not_disappear_from_exposure() -> None:
    report = currency_exposure(
        [OpenPosition("EUR_USD", long_units=Decimal("1000"), short_units=Decimal("-1000"))],
        conversion_rate=lambda source, target: Decimal("1") if source == target else Decimal("1.1"),
        account_currency="USD",
        mark_price=lambda instrument: Decimal("1.10"),
    )
    assert report.gross_account_value > 0
    assert report.gross_by_currency is not None and report.gross_by_currency["EUR"] > 0
    assert report.net_by_currency is not None and report.net_by_currency["EUR"] == 0


def test_synthetic_market_produces_structure_first_setup_evidence() -> None:
    market = SyntheticMarketData(seed=11, direction="long")
    assessment = assess_technicals(
        "EUR_USD",
        market.candles("EUR_USD", "M5", 200),
        market.candles("EUR_USD", "H1", 200),
    )
    assert assessment.direction.value == "long"
    assert assessment.liquidity_sweep is True
    assert assessment.structure_shift is True
    assert assessment.setup_family == "zone_liquidity_sweep_reclaim"
    assert assessment.liquidity_kind is not None
    assert assessment.stop_reference is not None
