from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from enum import StrEnum
from hashlib import sha256

from forex_trader.domain.enums import Direction
from forex_trader.domain.models import Candle


class ZoneKind(StrEnum):
    DEMAND = "demand"
    SUPPLY = "supply"


@dataclass(frozen=True, slots=True)
class Zone:
    zone_id: str
    kind: ZoneKind
    proximal: Decimal
    distal: Decimal
    origin_index: int
    created_at: object
    departure_multiple: Decimal
    touches: int
    penetration: Decimal
    freshness: Decimal
    quality: Decimal
    broken: bool

    @property
    def low(self) -> Decimal:
        return min(self.proximal, self.distal)

    @property
    def high(self) -> Decimal:
        return max(self.proximal, self.distal)

    def contains(self, price: Decimal) -> bool:
        return self.low <= price <= self.high

    def distance(self, price: Decimal) -> Decimal:
        if self.contains(price):
            return Decimal("0")
        return self.low - price if price < self.low else price - self.high


def detect_zones(
    candles: list[Candle],
    *,
    atr_value: Decimal,
    lookback: int = 140,
    departure_threshold: Decimal = Decimal("1.25"),
) -> list[Zone]:
    """Detect compact bases followed by impulsive departures and score later retests."""
    if atr_value <= 0:
        raise ValueError("atr_value must be positive")
    completed = [candle for candle in candles if candle.complete]
    if len(completed) < 8:
        return []
    start = max(1, len(completed) - lookback)
    zones: list[Zone] = []
    for index in range(start, len(completed) - 3):
        base = completed[index]
        base_range = base.high - base.low
        if base_range > atr_value * Decimal("1.15"):
            continue
        future = completed[index + 1 : index + 4]
        bullish_departure = max(candle.high for candle in future) - base.high
        bearish_departure = base.low - min(candle.low for candle in future)
        if bullish_departure >= atr_value * departure_threshold:
            zones.append(_make_zone(completed, index, ZoneKind.DEMAND, bullish_departure / atr_value))
        if bearish_departure >= atr_value * departure_threshold:
            zones.append(_make_zone(completed, index, ZoneKind.SUPPLY, bearish_departure / atr_value))
    # De-duplicate near-identical zones, preferring the newest/highest-quality instance.
    selected: list[Zone] = []
    for zone in sorted(zones, key=lambda item: (item.origin_index, item.quality), reverse=True):
        if zone.broken:
            continue
        if any(_overlap_ratio(zone, other) >= Decimal("0.75") for other in selected):
            continue
        selected.append(zone)
    return sorted(selected, key=lambda item: item.origin_index)


def _make_zone(candles: list[Candle], index: int, kind: ZoneKind, departure: Decimal) -> Zone:
    base = candles[index]
    if kind is ZoneKind.DEMAND:
        distal = base.low
        proximal = max(base.open, base.close)
    else:
        distal = base.high
        proximal = min(base.open, base.close)
    low, high = min(proximal, distal), max(proximal, distal)
    width = max(high - low, Decimal("0.00000001"))
    touches = 0
    max_penetration = Decimal("0")
    broken = False
    # Departure bars are not counted as retests.
    for candle in candles[index + 4 :]:
        intersects = candle.low <= high and candle.high >= low
        if intersects:
            touches += 1
            if kind is ZoneKind.DEMAND:
                depth = max(Decimal("0"), high - candle.low)
            else:
                depth = max(Decimal("0"), candle.high - low)
            max_penetration = max(max_penetration, min(Decimal("1"), depth / width))
        if kind is ZoneKind.DEMAND and candle.close < distal:
            broken = True
        if kind is ZoneKind.SUPPLY and candle.close > distal:
            broken = True
    freshness = Decimal("1") / Decimal(1 + touches)
    base_compactness = max(Decimal("0"), Decimal("1") - (base.high - base.low) / (width * Decimal("3")))
    departure_score = min(Decimal("1"), departure / Decimal("3"))
    quality = (
        departure_score * Decimal("0.50")
        + freshness * Decimal("0.35")
        + base_compactness * Decimal("0.15")
    )
    quality *= Decimal("1") - max_penetration * Decimal("0.35")
    raw_id = f"{kind.value}|{base.time.isoformat()}|{distal}|{proximal}"
    return Zone(
        zone_id=sha256(raw_id.encode()).hexdigest()[:20],
        kind=kind,
        proximal=proximal,
        distal=distal,
        origin_index=index,
        created_at=base.time,
        departure_multiple=departure,
        touches=touches,
        penetration=max_penetration,
        freshness=freshness,
        quality=max(Decimal("0"), min(Decimal("1"), quality)),
        broken=broken,
    )


def nearest_zone(
    zones: list[Zone],
    *,
    direction: Direction,
    price: Decimal,
    maximum_distance: Decimal,
    minimum_quality: Decimal = Decimal("0.35"),
) -> Zone | None:
    desired = ZoneKind.DEMAND if direction is Direction.LONG else ZoneKind.SUPPLY
    eligible = [
        zone
        for zone in zones
        if zone.kind is desired
        and not zone.broken
        and zone.quality >= minimum_quality
        and zone.distance(price) <= maximum_distance
    ]
    if not eligible:
        return None
    return min(eligible, key=lambda zone: (zone.distance(price), -zone.quality, -zone.origin_index))


def opposing_zones(zones: list[Zone], *, direction: Direction, price: Decimal) -> list[Zone]:
    desired = ZoneKind.SUPPLY if direction is Direction.LONG else ZoneKind.DEMAND
    if direction is Direction.LONG:
        eligible = [zone for zone in zones if zone.kind is desired and zone.low > price and not zone.broken]
        return sorted(eligible, key=lambda zone: zone.low)
    eligible = [zone for zone in zones if zone.kind is desired and zone.high < price and not zone.broken]
    return sorted(eligible, key=lambda zone: zone.high, reverse=True)


def _overlap_ratio(first: Zone, second: Zone) -> Decimal:
    overlap = max(Decimal("0"), min(first.high, second.high) - max(first.low, second.low))
    span = max(first.high - first.low, second.high - second.low, Decimal("0.00000001"))
    return overlap / span
