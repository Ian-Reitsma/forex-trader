from datetime import UTC, datetime, timedelta
from decimal import Decimal

from forex_trader.adapters.synthetic import SyntheticMarketData
from forex_trader.domain.enums import Direction
from forex_trader.domain.models import Candle
from forex_trader.domain.technicals import (
    _confirmed_post_shift_stop,
    assess_technicals,
    atr,
    ema,
    pip_size,
    rsi,
)


def test_indicators() -> None:
    values = [Decimal(index) for index in range(1, 31)]
    assert ema(values, 5) > Decimal("25")
    assert rsi(values, 14) == Decimal("100")


def test_atr_and_long_assessment() -> None:
    market = SyntheticMarketData(seed=4, direction="long")
    lower = market.candles("EUR_USD", "M5", 200)
    higher = market.candles("EUR_USD", "H1", 200)
    assert atr(lower) > 0
    assessment = assess_technicals("EUR_USD", lower, higher)
    assert assessment.direction is Direction.LONG
    assert assessment.score >= Decimal("0.60")
    assert assessment.stop_reference is not None
    assert assessment.take_profit_reference is not None


def test_short_assessment() -> None:
    market = SyntheticMarketData(seed=4, direction="short")
    assessment = assess_technicals(
        "USD_JPY",
        market.candles("USD_JPY", "M5", 200),
        market.candles("USD_JPY", "H1", 200),
    )
    assert assessment.direction is Direction.SHORT
    assert pip_size("USD_JPY") == Decimal("0.01")


def test_confirmed_post_shift_pivot_can_only_tighten_long_stop() -> None:
    start = datetime(2026, 8, 10, 12, 0, tzinfo=UTC)
    candles = [
        Candle(start, Decimal("1.0990"), Decimal("1.1005"), Decimal("1.0988"), Decimal("1.1002")),
        Candle(start + timedelta(minutes=5), Decimal("1.1002"), Decimal("1.1015"), Decimal("1.1005"), Decimal("1.1012")),
        Candle(start + timedelta(minutes=10), Decimal("1.1012"), Decimal("1.1022"), Decimal("1.1010"), Decimal("1.1020")),
        Candle(start + timedelta(minutes=15), Decimal("1.1020"), Decimal("1.1021"), Decimal("1.1004"), Decimal("1.1010")),
        Candle(start + timedelta(minutes=20), Decimal("1.1010"), Decimal("1.1027"), Decimal("1.1012"), Decimal("1.1025")),
        Candle(start + timedelta(minutes=25), Decimal("1.1025"), Decimal("1.1033"), Decimal("1.1020"), Decimal("1.1030")),
    ]
    baseline = Decimal("1.0980")
    tightened = _confirmed_post_shift_stop(
        candles,
        direction=Direction.LONG,
        shift_index=0,
        entry=Decimal("1.1030"),
        baseline_stop=baseline,
        buffer=Decimal("0.0001"),
    )
    assert tightened == Decimal("1.1003")
    assert baseline < tightened < Decimal("1.1030")


def test_post_shift_stop_keeps_baseline_without_confirmed_pivot() -> None:
    start = datetime(2026, 8, 10, 12, 0, tzinfo=UTC)
    candles = [
        Candle(start, Decimal("1.1000"), Decimal("1.1005"), Decimal("1.0995"), Decimal("1.1002")),
        Candle(start + timedelta(minutes=5), Decimal("1.1002"), Decimal("1.1010"), Decimal("1.1000"), Decimal("1.1008")),
        Candle(start + timedelta(minutes=10), Decimal("1.1008"), Decimal("1.1015"), Decimal("1.1006"), Decimal("1.1012")),
    ]
    baseline = Decimal("1.0980")
    assert _confirmed_post_shift_stop(
        candles,
        direction=Direction.LONG,
        shift_index=0,
        entry=Decimal("1.1012"),
        baseline_stop=baseline,
        buffer=Decimal("0.0001"),
    ) == baseline
