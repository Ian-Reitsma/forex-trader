from datetime import UTC, datetime, timedelta
from decimal import Decimal

from forex_trader.domain.enums import Direction
from forex_trader.domain.liquidity import (
    LiquidityKind,
    LiquidityLevel,
    build_liquidity_map,
    find_recent_sweep,
)
from forex_trader.domain.models import Candle
from forex_trader.domain.risk_day import fx_bar_risk_day_key, fx_bar_week_key


def bar(
    when: datetime,
    *,
    high: Decimal = Decimal("1.1010"),
    low: Decimal = Decimal("1.0990"),
    close: Decimal = Decimal("1.1000"),
) -> Candle:
    open_ = close
    return Candle(when, open_, high, low, close, 100)


def series(start: datetime, count: int, step: timedelta) -> list[Candle]:
    return [bar(start + step * index) for index in range(count)]


def by_kind(levels: list[LiquidityLevel], kind: LiquidityKind) -> LiquidityLevel:
    return next(level for level in levels if level.kind is kind)


def test_bar_ending_at_5pm_new_york_stays_in_day_that_closed() -> None:
    # August DST: 5 p.m. New York is 21:00 UTC. The 20:00-21:00 bar belongs to
    # the risk day that started the prior calendar date, while 21:00-22:00 is new day.
    assert fx_bar_risk_day_key(
        datetime(2026, 8, 7, 20, tzinfo=UTC), timedelta(hours=1)
    ) == "2026-08-06"
    assert fx_bar_risk_day_key(
        datetime(2026, 8, 7, 21, tzinfo=UTC), timedelta(hours=1)
    ) == "2026-08-07"


def test_prior_day_extremes_use_5pm_new_york_boundary() -> None:
    candles = series(datetime(2026, 8, 6, 21, tzinfo=UTC), 27, timedelta(hours=1))
    # This bar ends exactly at Friday's 5 p.m. New York boundary and must remain
    # part of the day that just closed.
    candles[23] = bar(
        datetime(2026, 8, 7, 20, tzinfo=UTC),
        high=Decimal("1.2500"),
        low=Decimal("0.9500"),
        close=Decimal("1.1000"),
    )
    levels = build_liquidity_map(candles, pip_size=Decimal("0.0001"))
    assert by_kind(levels, LiquidityKind.PRIOR_DAY_HIGH).price == Decimal("1.2500")
    assert by_kind(levels, LiquidityKind.PRIOR_DAY_LOW).price == Decimal("0.9500")


def test_fx_week_rolls_on_sunday_5pm_new_york_not_iso_monday() -> None:
    # Sunday 20:00-21:00 UTC still belongs to the prior FX week; the next bar is new week.
    prior = fx_bar_week_key(datetime(2026, 8, 9, 20, tzinfo=UTC), timedelta(hours=1))
    new = fx_bar_week_key(datetime(2026, 8, 9, 21, tzinfo=UTC), timedelta(hours=1))
    assert prior == "2026-08-02"
    assert new == "2026-08-09"


def test_prior_week_extremes_come_from_higher_timeframe_context() -> None:
    lower = series(datetime(2026, 8, 11, 12, tzinfo=UTC), 24, timedelta(minutes=5))
    context = series(datetime(2026, 8, 2, 21, tzinfo=UTC), 54, timedelta(hours=4))
    # The bar starting Sunday 17:00 UTC ends at 21:00 UTC / 5 p.m. New York,
    # so its range is still part of the week that began August 2.
    boundary_index = next(
        index
        for index, candle in enumerate(context)
        if candle.time == datetime(2026, 8, 9, 17, tzinfo=UTC)
    )
    context[boundary_index] = bar(
        context[boundary_index].time,
        high=Decimal("1.4000"),
        low=Decimal("0.8000"),
        close=Decimal("1.1000"),
    )
    levels = build_liquidity_map(
        lower,
        pip_size=Decimal("0.0001"),
        context_candles=context,
    )
    assert by_kind(levels, LiquidityKind.PRIOR_WEEK_HIGH).price == Decimal("1.4000")
    assert by_kind(levels, LiquidityKind.PRIOR_WEEK_LOW).price == Decimal("0.8000")


def test_asia_liquidity_is_declared_only_after_session_finishes() -> None:
    # Tokyo 09:00-18:00 local is 00:00-09:00 UTC in August.
    completed = series(datetime(2026, 8, 7, 0, tzinfo=UTC), 120, timedelta(minutes=5))
    completed[20] = bar(
        completed[20].time,
        high=Decimal("1.2200"),
        low=Decimal("0.9800"),
        close=Decimal("1.1000"),
    )
    levels = build_liquidity_map(completed, pip_size=Decimal("0.0001"))
    assert by_kind(levels, LiquidityKind.ASIA_HIGH).price == Decimal("1.2200")
    assert by_kind(levels, LiquidityKind.ASIA_LOW).price == Decimal("0.9800")

    partial = series(datetime(2026, 8, 8, 0, tzinfo=UTC), 48, timedelta(minutes=5))
    partial_levels = build_liquidity_map(partial, pip_size=Decimal("0.0001"))
    assert not any(level.kind in {LiquidityKind.ASIA_HIGH, LiquidityKind.ASIA_LOW} for level in partial_levels)


def test_london_and_new_york_opening_ranges_finalize_after_30_minutes() -> None:
    # London 08:00 BST == 07:00 UTC. NY 08:00 EDT == 12:00 UTC.
    candles = series(datetime(2026, 8, 7, 6, 30, tzinfo=UTC), 90, timedelta(minutes=5))
    london_members = [
        index for index, candle in enumerate(candles)
        if datetime(2026, 8, 7, 7, tzinfo=UTC) <= candle.time < datetime(2026, 8, 7, 7, 30, tzinfo=UTC)
    ]
    ny_members = [
        index for index, candle in enumerate(candles)
        if datetime(2026, 8, 7, 12, tzinfo=UTC) <= candle.time < datetime(2026, 8, 7, 12, 30, tzinfo=UTC)
    ]
    candles[london_members[2]] = bar(
        candles[london_members[2]].time,
        high=Decimal("1.1800"),
        low=Decimal("1.0200"),
        close=Decimal("1.1000"),
    )
    candles[ny_members[3]] = bar(
        candles[ny_members[3]].time,
        high=Decimal("1.1900"),
        low=Decimal("1.0100"),
        close=Decimal("1.1000"),
    )
    levels = build_liquidity_map(candles, pip_size=Decimal("0.0001"))
    assert by_kind(levels, LiquidityKind.LONDON_OPEN_HIGH).price == Decimal("1.1800")
    assert by_kind(levels, LiquidityKind.LONDON_OPEN_LOW).price == Decimal("1.0200")
    assert by_kind(levels, LiquidityKind.NEW_YORK_OPEN_HIGH).price == Decimal("1.1900")
    assert by_kind(levels, LiquidityKind.NEW_YORK_OPEN_LOW).price == Decimal("1.0100")

    partial_london = series(datetime(2026, 8, 10, 7, tzinfo=UTC), 4, timedelta(minutes=5))
    # Add earlier neutral history so build_liquidity_map has enough bars, while the
    # current opening range itself remains unfinished at 07:20 UTC.
    history = series(datetime(2026, 8, 10, 6, tzinfo=UTC), 12, timedelta(minutes=5))
    partial_levels = build_liquidity_map(
        [*history, *partial_london], pip_size=Decimal("0.0001")
    )
    assert not any(
        level.kind in {LiquidityKind.LONDON_OPEN_HIGH, LiquidityKind.LONDON_OPEN_LOW}
        for level in partial_levels
    )


def test_level_cannot_be_swept_by_candle_that_created_it() -> None:
    candles = series(datetime(2026, 8, 7, 12, tzinfo=UTC), 12, timedelta(minutes=5))
    current = candles[-1]
    candles[-1] = bar(
        current.time,
        high=Decimal("1.1010"),
        low=Decimal("1.0980"),
        close=Decimal("1.1000"),
    )
    level = LiquidityLevel(
        LiquidityKind.EXTERNAL_SWING_LOW,
        Decimal("1.0990"),
        Decimal("0.9"),
        source_time=candles[-1].time,
    )
    assert find_recent_sweep(
        candles,
        [level],
        pip_size=Decimal("0.0001"),
        max_bars=1,
    ) is None


def test_preexisting_declared_level_can_be_swept_and_reclaimed() -> None:
    candles = series(datetime(2026, 8, 7, 12, tzinfo=UTC), 12, timedelta(minutes=5))
    current = candles[-1]
    candles[-1] = bar(
        current.time,
        high=Decimal("1.1010"),
        low=Decimal("1.0980"),
        close=Decimal("1.1000"),
    )
    level = LiquidityLevel(
        LiquidityKind.PRIOR_DAY_LOW,
        Decimal("1.0990"),
        Decimal("1"),
        source_time=candles[-2].time,
    )
    sweep = find_recent_sweep(candles, [level], pip_size=Decimal("0.0001"), max_bars=1)
    assert sweep is not None
    assert sweep.direction is Direction.LONG
    assert sweep.level.kind is LiquidityKind.PRIOR_DAY_LOW
