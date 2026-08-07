from datetime import UTC, datetime, timedelta
from decimal import Decimal

from forex_trader.domain.costs import SessionCostModel, TradingSession, trading_session
from forex_trader.domain.models import Quote


def test_trading_session_boundaries_are_utc() -> None:
    assert trading_session(datetime(2026, 1, 1, 2, tzinfo=UTC)) is TradingSession.ASIA
    assert trading_session(datetime(2026, 1, 1, 8, tzinfo=UTC)) is TradingSession.LONDON
    assert trading_session(datetime(2026, 1, 1, 13, tzinfo=UTC)) is TradingSession.LONDON_NEW_YORK
    assert trading_session(datetime(2026, 1, 1, 18, tzinfo=UTC)) is TradingSession.NEW_YORK
    assert trading_session(datetime(2026, 1, 1, 22, tzinfo=UTC)) is TradingSession.OFF_HOURS


def test_session_cost_model_can_only_tighten_hard_spread_limit() -> None:
    model = SessionCostModel(minimum_samples=3)
    base = datetime(2026, 1, 1, 8, tzinfo=UTC)
    for index, spread in enumerate(("0.5", "0.6", "0.7")):
        half = Decimal(spread) * Decimal("0.0001") / Decimal("2")
        model.record_quote(
            Quote("EUR_USD", Decimal("1.1") - half, Decimal("1.1") + half, base + timedelta(minutes=index))
        )
    profile = model.profile("EUR_USD", base)
    assert profile is not None
    learned = model.spread_limit("EUR_USD", base, configured_maximum=Decimal("2"))
    assert learned <= Decimal("2")
    assert learned >= profile.p90_spread_pips


def test_slippage_is_recorded_in_pips() -> None:
    model = SessionCostModel(minimum_samples=1)
    sample = model.record_slippage(
        instrument="EUR_USD",
        observed_at=datetime(2026, 1, 1, 8, tzinfo=UTC),
        intended_price=Decimal("1.10000"),
        fill_price=Decimal("1.10005"),
    )
    assert sample.slippage_pips == Decimal("0.5")
