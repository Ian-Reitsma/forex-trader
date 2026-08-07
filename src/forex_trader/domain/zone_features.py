from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

from forex_trader.domain.enums import Direction
from forex_trader.domain.models import Candle
from forex_trader.domain.zones import Zone


@dataclass(frozen=True, slots=True)
class ZoneFeatures:
    zone_id: str
    origin_timeframe: str
    base_candle_count: int
    departure_atr: Decimal
    departure_speed: Decimal
    imbalance_evidence: Decimal
    flow_alignment: Decimal
    retests: int
    penetration: Decimal
    age_seconds: Decimal
    time_inside_seconds: Decimal
    renewed_displacement: Decimal
    higher_timeframe_alignment: Decimal
    liquidity_proximity_atr: Decimal
    event_created: bool

    def as_model_features(self) -> dict[str, str | int | bool]:
        return {
            "zone_id": self.zone_id,
            "origin_timeframe": self.origin_timeframe,
            "base_candle_count": self.base_candle_count,
            "departure_atr": str(self.departure_atr),
            "departure_speed": str(self.departure_speed),
            "imbalance_evidence": str(self.imbalance_evidence),
            "flow_alignment": str(self.flow_alignment),
            "retests": self.retests,
            "penetration": str(self.penetration),
            "age_seconds": str(self.age_seconds),
            "time_inside_seconds": str(self.time_inside_seconds),
            "renewed_displacement": str(self.renewed_displacement),
            "higher_timeframe_alignment": str(self.higher_timeframe_alignment),
            "liquidity_proximity_atr": str(self.liquidity_proximity_atr),
            "event_created": self.event_created,
        }


def derive_zone_features(
    zone: Zone,
    candles: list[Candle],
    *,
    origin_timeframe: str,
    as_of: datetime,
    atr_value: Decimal,
    higher_timeframe_direction: Direction = Direction.FLAT,
    flow_alignment: Decimal = Decimal("0"),
    liquidity_distance_atr: Decimal = Decimal("0"),
    event_created: bool = False,
) -> ZoneFeatures:
    """Expose zone attributes without inventing another production quality formula.

    The current runtime quality remains untouched. These raw, point-in-time attributes are
    intended for leakage-controlled calibration/ablation before any new weighting receives
    Practice authority.
    """
    if as_of.tzinfo is None:
        raise ValueError("as_of must be timezone-aware")
    if atr_value <= 0:
        raise ValueError("atr_value must be positive")
    completed = sorted((item for item in candles if item.complete and item.time <= as_of), key=lambda item: item.time)
    if not completed:
        raise ValueError("at least one point-in-time candle is required")
    origin = next((item for item in completed if item.time == zone.created_at), None)
    if origin is None:
        origin = completed[max(0, min(zone.origin_index, len(completed) - 1))]
    origin_index = completed.index(origin)
    post = completed[origin_index + 1 :]
    base_count = 1
    for prior in reversed(completed[max(0, origin_index - 3) : origin_index]):
        if prior.high >= zone.low and prior.low <= zone.high:
            base_count += 1
        else:
            break
    departure_window = post[:3]
    departure_speed = Decimal("0")
    if departure_window:
        distances = [max(abs(item.high - zone.high), abs(zone.low - item.low)) / atr_value for item in departure_window]
        departure_speed = max(distances) / Decimal(max(1, len(departure_window)))
    inside = [item for item in post if item.low <= zone.high and item.high >= zone.low]
    if len(completed) >= 2:
        default_step = max(Decimal("1"), Decimal(str((completed[-1].time - completed[-2].time).total_seconds())))
    else:
        default_step = Decimal("0")
    time_inside = default_step * Decimal(len(inside))
    width = max(zone.high - zone.low, Decimal("0.00000001"))
    imbalance = Decimal("0")
    for first, second in zip(post, post[1:]):
        if first.high < second.low or first.low > second.high:
            gap = second.low - first.high if first.high < second.low else first.low - second.high
            imbalance = max(imbalance, min(Decimal("1"), abs(gap) / max(width, atr_value)))
    renewed = Decimal("0")
    if inside:
        last_touch = completed.index(inside[-1])
        after_touch = completed[last_touch + 1 :]
        if after_touch:
            if zone.kind.value == "demand":
                move = max((item.high - zone.high for item in after_touch), default=Decimal("0"))
            else:
                move = max((zone.low - item.low for item in after_touch), default=Decimal("0"))
            renewed = max(Decimal("0"), move / atr_value)
    desired = Direction.LONG if zone.kind.value == "demand" else Direction.SHORT
    htf_alignment = Decimal("1") if higher_timeframe_direction is desired else Decimal("0") if higher_timeframe_direction is Direction.FLAT else Decimal("-1")
    return ZoneFeatures(
        zone_id=zone.zone_id,
        origin_timeframe=origin_timeframe.upper(),
        base_candle_count=base_count,
        departure_atr=zone.departure_multiple,
        departure_speed=max(Decimal("0"), departure_speed),
        imbalance_evidence=imbalance,
        flow_alignment=max(Decimal("-1"), min(Decimal("1"), flow_alignment)),
        retests=zone.touches,
        penetration=zone.penetration,
        age_seconds=max(Decimal("0"), Decimal(str((as_of - origin.time).total_seconds()))),
        time_inside_seconds=max(Decimal("0"), time_inside),
        renewed_displacement=renewed,
        higher_timeframe_alignment=htf_alignment,
        liquidity_proximity_atr=max(Decimal("0"), liquidity_distance_atr),
        event_created=event_created,
    )
