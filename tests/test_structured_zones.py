from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from forex_trader.domain.enums import Direction
from forex_trader.domain.models import Candle
from forex_trader.domain.zones import ZoneKind
from forex_trader.research.structured_zones import (
    StructuredZoneDetectionPolicy,
    StructuredZonePattern,
    by_pattern,
    detect_structured_zones,
)

NOW = datetime(2026, 7, 7, 12, 0, tzinfo=UTC)
ATR = Decimal("0.0010")


def _candle(index: int, open_: str, high: str, low: str, close: str) -> Candle:
    return Candle(
        time=NOW + timedelta(minutes=5 * index),
        open=Decimal(open_),
        high=Decimal(high),
        low=Decimal(low),
        close=Decimal(close),
        volume=100 + index,
    )


def _scenario(pattern: StructuredZonePattern) -> list[Candle]:
    rally = [
        ("1.0988", "1.0995", "1.0987", "1.0994"),
        ("1.0994", "1.1001", "1.0993", "1.1000"),
        ("1.1000", "1.1008", "1.0999", "1.1007"),
    ]
    drop = [
        ("1.1026", "1.1027", "1.1019", "1.1020"),
        ("1.1020", "1.1021", "1.1013", "1.1014"),
        ("1.1014", "1.1015", "1.1006", "1.1007"),
    ]
    base = [
        ("1.1007", "1.1010", "1.1005", "1.1008"),
        ("1.1008", "1.1011", "1.1006", "1.1007"),
    ]
    departure_up = [
        ("1.1008", "1.1017", "1.1007", "1.1016"),
        ("1.1016", "1.1025", "1.1015", "1.1024"),
        ("1.1024", "1.1028", "1.1023", "1.1027"),
    ]
    departure_down = [
        ("1.1007", "1.1008", "1.0998", "1.0999"),
        ("1.0999", "1.1000", "1.0989", "1.0990"),
        ("1.0990", "1.0991", "1.0985", "1.0986"),
    ]
    arrival = rally if pattern.arrival_direction is Direction.LONG else drop
    departure = departure_up if pattern.departure_direction is Direction.LONG else departure_down
    return [
        _candle(index, *values)
        for index, values in enumerate((*arrival, *base, *departure))
    ]


@pytest.mark.parametrize("pattern", tuple(StructuredZonePattern))
def test_detects_public_four_pattern_taxonomy(pattern: StructuredZonePattern) -> None:
    zones = detect_structured_zones(_scenario(pattern), atr_value=ATR)
    matched = by_pattern(zones, pattern)
    assert matched, f"missing {pattern.value}"
    best = max(matched, key=lambda item: item.research_quality)
    assert best.base_candle_count >= 1
    assert best.base_candle_count <= 4
    assert best.departure_atr >= Decimal("1.25")
    assert best.departure_speed_atr_per_bar > 0
    assert best.zone.kind is pattern.kind
    assert best.zone.broken is False


def test_multicandle_base_is_preserved_as_research_metadata() -> None:
    policy = StructuredZoneDetectionPolicy(min_base_candles=2, max_base_candles=2)
    zones = detect_structured_zones(
        _scenario(StructuredZonePattern.RALLY_BASE_RALLY),
        atr_value=ATR,
        policy=policy,
    )
    matched = by_pattern(zones, StructuredZonePattern.RALLY_BASE_RALLY)
    assert len(matched) == 1
    zone = matched[0]
    assert zone.base_candle_count == 2
    assert zone.base_end_index - zone.base_start_index == 1
    assert zone.body_overlap >= 0
    assert zone.base_width_atr > 0
    assert zone.zone.kind is ZoneKind.DEMAND


def test_retest_freshness_uses_only_information_available_as_of() -> None:
    candles = _scenario(StructuredZonePattern.RALLY_BASE_RALLY)
    initial_as_of = candles[-1].time
    retest = _candle(8, "1.1025", "1.1026", "1.1008", "1.1020")
    candles.append(retest)

    before = by_pattern(
        detect_structured_zones(candles, atr_value=ATR, as_of=initial_as_of),
        StructuredZonePattern.RALLY_BASE_RALLY,
    )
    after = by_pattern(
        detect_structured_zones(candles, atr_value=ATR, as_of=retest.time),
        StructuredZonePattern.RALLY_BASE_RALLY,
    )

    assert before and after
    assert before[0].zone.touches == 0
    assert before[0].zone.freshness == Decimal("1")
    assert after[0].zone.touches >= 1
    assert after[0].zone.freshness < Decimal("1")


def test_future_break_does_not_invalidate_earlier_snapshot() -> None:
    candles = _scenario(StructuredZonePattern.RALLY_BASE_RALLY)
    clean_as_of = candles[-1].time
    breaker = _candle(8, "1.1010", "1.1011", "1.0998", "1.1000")
    candles.append(breaker)

    before = by_pattern(
        detect_structured_zones(candles, atr_value=ATR, as_of=clean_as_of),
        StructuredZonePattern.RALLY_BASE_RALLY,
    )
    after = by_pattern(
        detect_structured_zones(candles, atr_value=ATR, as_of=breaker.time),
        StructuredZonePattern.RALLY_BASE_RALLY,
    )

    assert before
    assert before[0].zone.broken is False
    assert after == ()


def test_as_of_and_policy_validation_fail_closed() -> None:
    with pytest.raises(ValueError):
        detect_structured_zones([], atr_value=Decimal("0"))
    with pytest.raises(ValueError):
        detect_structured_zones([], atr_value=ATR, as_of=datetime(2026, 1, 1))
    with pytest.raises(ValueError):
        StructuredZoneDetectionPolicy(min_base_candles=0)
    with pytest.raises(ValueError):
        StructuredZoneDetectionPolicy(arrival_bars=0)
