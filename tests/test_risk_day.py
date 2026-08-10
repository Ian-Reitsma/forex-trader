from datetime import UTC, datetime
from decimal import Decimal
from types import SimpleNamespace

from forex_trader.application.fx_engine import FxTradingEngine
from forex_trader.domain.risk_day import fx_risk_day_bounds, fx_risk_day_key


def test_fx_risk_day_uses_5pm_new_york_in_winter_and_summer() -> None:
    winter = datetime(2026, 1, 15, 23, 0, tzinfo=UTC)
    winter_start, winter_end = fx_risk_day_bounds(winter)
    assert winter_start == datetime(2026, 1, 15, 22, 0, tzinfo=UTC)
    assert winter_end == datetime(2026, 1, 16, 22, 0, tzinfo=UTC)
    assert fx_risk_day_key(winter) == "2026-01-15"

    summer = datetime(2026, 8, 7, 22, 0, tzinfo=UTC)
    summer_start, summer_end = fx_risk_day_bounds(summer)
    assert summer_start == datetime(2026, 8, 7, 21, 0, tzinfo=UTC)
    assert summer_end == datetime(2026, 8, 8, 21, 0, tzinfo=UTC)
    assert fx_risk_day_key(summer) == "2026-08-07"


def test_fx_risk_day_before_close_belongs_to_prior_new_york_day() -> None:
    instant = datetime(2026, 8, 7, 20, 59, tzinfo=UTC)
    start, end = fx_risk_day_bounds(instant)
    assert start == datetime(2026, 8, 6, 21, 0, tzinfo=UTC)
    assert end == datetime(2026, 8, 7, 21, 0, tzinfo=UTC)
    assert fx_risk_day_key(instant) == "2026-08-06"


def test_fx_risk_day_requires_timezone_aware_timestamp() -> None:
    try:
        fx_risk_day_bounds(datetime(2026, 8, 7, 12))
    except ValueError as exc:
        assert "timezone-aware" in str(exc)
    else:
        raise AssertionError("naive risk-day timestamp should fail")


def test_fx_engine_persistent_loss_latch_uses_fx_day_key() -> None:
    captured: dict[str, object] = {}

    class Repository:
        def observe_risk_day(self, **kwargs):  # type: ignore[no-untyped-def]
            captured.update(kwargs)
            return True

    engine = SimpleNamespace(
        repository=Repository(),
        risk_policy=SimpleNamespace(max_daily_loss_fraction=Decimal("0.01")),
    )
    account = SimpleNamespace(
        account_id="A",
        realized_pl_today=Decimal("-60"),
        unrealized_pl=Decimal("-50"),
    )
    result = FxTradingEngine._observe_latched_loss(  # type: ignore[misc]
        engine,
        account,
        datetime(2026, 8, 7, 20, 59, tzinfo=UTC),
        Decimal("10000"),
    )
    assert result is True
    assert captured["trading_day"] == "2026-08-06"
    assert captured["marked_pl"] == Decimal("-110")
    assert captured["loss_limit_amount"] == Decimal("100.00")
