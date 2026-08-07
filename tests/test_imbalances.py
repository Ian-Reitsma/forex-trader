from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from forex_trader.domain.enums import Direction
from forex_trader.domain.imbalances import (
    detect_fair_value_gaps,
    fvg_zone_overlap_fraction,
    nearest_open_fvg,
)
from forex_trader.domain.models import Candle


def candle(index: int, open_: str, high: str, low: str, close: str) -> Candle:
    return Candle(
        datetime(2026, 8, 7, tzinfo=UTC) + timedelta(minutes=5 * index),
        Decimal(open_),
        Decimal(high),
        Decimal(low),
        Decimal(close),
    )


def test_detects_bullish_fvg_and_partial_mitigation() -> None:
    candles = [
        candle(0, "1.1000", "1.1010", "1.0990", "1.1005"),
        candle(1, "1.1005", "1.1030", "1.1002", "1.1028"),
        candle(2, "1.1028", "1.1040", "1.1020", "1.1035"),
        candle(3, "1.1035", "1.1040", "1.1015", "1.1030"),
    ]
    gaps = detect_fair_value_gaps(candles, minimum_gap=Decimal("0.0005"))
    bullish = [gap for gap in gaps if gap.direction is Direction.LONG]
    assert bullish
    gap = bullish[0]
    assert gap.lower == Decimal("1.1010")
    assert gap.upper == Decimal("1.1020")
    assert gap.touched is True
    assert gap.fully_mitigated is False
    assert gap.fill_fraction == Decimal("0.5")


def test_detects_bearish_fvg_and_full_mitigation() -> None:
    candles = [
        candle(0, "1.1050", "1.1060", "1.1040", "1.1045"),
        candle(1, "1.1045", "1.1048", "1.1010", "1.1012"),
        candle(2, "1.1012", "1.1025", "1.1005", "1.1010"),
        candle(3, "1.1010", "1.1045", "1.1008", "1.1035"),
    ]
    gaps = detect_fair_value_gaps(candles, minimum_gap=Decimal("0.0005"))
    bearish = [gap for gap in gaps if gap.direction is Direction.SHORT]
    assert bearish
    gap = bearish[0]
    assert gap.lower == Decimal("1.1025")
    assert gap.upper == Decimal("1.1040")
    assert gap.touched is True
    assert gap.fully_mitigated is True
    assert gap.fill_fraction == Decimal("1")


def test_nearest_open_fvg_and_zone_overlap_are_descriptive_features() -> None:
    candles = [
        candle(0, "1.1000", "1.1010", "1.0990", "1.1005"),
        candle(1, "1.1005", "1.1030", "1.1002", "1.1028"),
        candle(2, "1.1028", "1.1040", "1.1020", "1.1035"),
    ]
    gap = detect_fair_value_gaps(candles)[0]
    nearest = nearest_open_fvg(
        [gap],
        direction=Direction.LONG,
        price=Decimal("1.1021"),
        maximum_distance=Decimal("0.0010"),
    )
    assert nearest == gap
    assert fvg_zone_overlap_fraction(
        gap,
        zone_low=Decimal("1.1015"),
        zone_high=Decimal("1.1025"),
    ) == Decimal("0.5")
    assert nearest_open_fvg(
        [gap],
        direction=Direction.SHORT,
        price=Decimal("1.1021"),
        maximum_distance=Decimal("0.0010"),
    ) is None


def test_fvg_feature_validates_inputs_and_short_history() -> None:
    assert detect_fair_value_gaps([]) == []
    with pytest.raises(ValueError, match="minimum_gap"):
        detect_fair_value_gaps([], minimum_gap=Decimal("-0.1"))
    with pytest.raises(ValueError, match="lookback"):
        detect_fair_value_gaps([], lookback=2)
    with pytest.raises(ValueError, match="maximum_distance"):
        nearest_open_fvg([], direction=Direction.LONG, price=Decimal("1"), maximum_distance=Decimal("-1"))
