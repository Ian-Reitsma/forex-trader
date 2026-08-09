from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from enum import StrEnum
from hashlib import sha256
from typing import Iterable, Sequence

from forex_trader.domain.enums import Direction
from forex_trader.domain.models import Candle
from forex_trader.domain.zones import Zone, ZoneKind


class StructuredZonePattern(StrEnum):
    """Public supply/demand base archetypes represented as measurable research labels."""

    RALLY_BASE_RALLY = "RBR"
    RALLY_BASE_DROP = "RBD"
    DROP_BASE_RALLY = "DBR"
    DROP_BASE_DROP = "DBD"

    @property
    def kind(self) -> ZoneKind:
        if self in {StructuredZonePattern.RALLY_BASE_RALLY, StructuredZonePattern.DROP_BASE_RALLY}:
            return ZoneKind.DEMAND
        return ZoneKind.SUPPLY

    @property
    def arrival_direction(self) -> Direction:
        if self in {StructuredZonePattern.RALLY_BASE_RALLY, StructuredZonePattern.RALLY_BASE_DROP}:
            return Direction.LONG
        return Direction.SHORT

    @property
    def departure_direction(self) -> Direction:
        return Direction.LONG if self.kind is ZoneKind.DEMAND else Direction.SHORT


@dataclass(frozen=True, slots=True)
class StructuredZone:
    """Research-only structured zone; ``zone`` remains compatible with existing features."""

    zone: Zone
    pattern: StructuredZonePattern
    base_start_index: int
    base_end_index: int
    base_candle_count: int
    arrival_atr: Decimal
    departure_atr: Decimal
    departure_bars: int
    departure_speed_atr_per_bar: Decimal
    base_width_atr: Decimal
    body_overlap: Decimal
    imbalance_evidence: Decimal
    age_bars: int
    research_quality: Decimal

    def __post_init__(self) -> None:
        if self.base_start_index < 0 or self.base_end_index < self.base_start_index:
            raise ValueError("invalid structured-zone base indexes")
        if self.base_candle_count != self.base_end_index - self.base_start_index + 1:
            raise ValueError("base_candle_count does not match base indexes")
        if self.zone.kind is not self.pattern.kind:
            raise ValueError("zone kind must agree with structured pattern")
        if self.departure_bars < 1:
            raise ValueError("departure_bars must be positive")
        for value in (
            self.arrival_atr,
            self.departure_atr,
            self.departure_speed_atr_per_bar,
            self.base_width_atr,
            self.body_overlap,
            self.imbalance_evidence,
            self.research_quality,
        ):
            if value < 0:
                raise ValueError("structured-zone metrics cannot be negative")
        if self.research_quality > 1 or self.body_overlap > 1 or self.imbalance_evidence > 1:
            raise ValueError("bounded structured-zone metrics must be <= 1")


@dataclass(frozen=True, slots=True)
class StructuredZoneDetectionPolicy:
    min_base_candles: int = 1
    max_base_candles: int = 4
    maximum_base_width_atr: Decimal = Decimal("1.35")
    maximum_base_candle_range_atr: Decimal = Decimal("0.90")
    minimum_arrival_atr: Decimal = Decimal("0.75")
    minimum_departure_atr: Decimal = Decimal("1.25")
    arrival_bars: int = 3
    departure_bars: int = 3
    maximum_research_age_bars: int = 200

    def __post_init__(self) -> None:
        if self.min_base_candles < 1 or self.max_base_candles < self.min_base_candles:
            raise ValueError("invalid base-candle bounds")
        if self.arrival_bars < 1 or self.departure_bars < 1:
            raise ValueError("arrival/departure windows must be positive")
        if self.maximum_research_age_bars < 1:
            raise ValueError("maximum_research_age_bars must be positive")
        if self.maximum_base_width_atr <= 0 or self.maximum_base_candle_range_atr <= 0:
            raise ValueError("base width limits must be positive")
        if self.minimum_arrival_atr <= 0 or self.minimum_departure_atr <= 0:
            raise ValueError("arrival/departure thresholds must be positive")


def detect_structured_zones(
    candles: Sequence[Candle],
    *,
    atr_value: Decimal,
    as_of: datetime | None = None,
    policy: StructuredZoneDetectionPolicy = StructuredZoneDetectionPolicy(),
) -> tuple[StructuredZone, ...]:
    """Detect research-only multi-candle supply/demand bases without future leakage.

    Detection needs a directional arrival, one-to-four compact base candles, and a
    sufficiently impulsive departure. Only completed candles available by ``as_of`` are
    eligible. Retest/freshness attributes on the embedded ``Zone`` are also calculated
    only from candles already available by that timestamp.

    This function intentionally does *not* replace ``domain.zones.detect_zones``. The
    archetype and thresholds require leakage-controlled ablation before any Practice
    policy can depend on them.
    """

    if atr_value <= 0:
        raise ValueError("atr_value must be positive")
    if as_of is not None and as_of.tzinfo is None:
        raise ValueError("as_of must be timezone-aware")
    available = [
        candle
        for candle in candles
        if candle.complete and (as_of is None or candle.time <= as_of)
    ]
    available.sort(key=lambda item: item.time)
    if len(available) < policy.arrival_bars + policy.min_base_candles + policy.departure_bars:
        return ()

    latest_start = max(0, len(available) - policy.maximum_research_age_bars)
    candidates: list[StructuredZone] = []
    for base_start in range(max(policy.arrival_bars, latest_start), len(available)):
        for base_count in range(policy.min_base_candles, policy.max_base_candles + 1):
            base_end = base_start + base_count - 1
            departure_end = base_end + policy.departure_bars
            if departure_end >= len(available):
                break
            base = available[base_start : base_end + 1]
            if not _compact_base(base, atr_value=atr_value, policy=policy):
                continue
            arrival = available[base_start - policy.arrival_bars : base_start]
            departure = available[base_end + 1 : departure_end + 1]
            arrival_direction, arrival_atr = _arrival(arrival, atr_value=atr_value)
            if arrival_direction is Direction.FLAT or arrival_atr < policy.minimum_arrival_atr:
                continue
            departure_direction, departure_atr, departure_bars = _departure(
                base,
                departure,
                atr_value=atr_value,
            )
            if departure_direction is Direction.FLAT or departure_atr < policy.minimum_departure_atr:
                continue
            pattern = _pattern(arrival_direction, departure_direction)
            if pattern is None:
                continue
            candidates.append(
                _build_structured_zone(
                    available,
                    base_start=base_start,
                    base_end=base_end,
                    departure_end=departure_end,
                    pattern=pattern,
                    arrival_atr=arrival_atr,
                    departure_atr=departure_atr,
                    departure_bars=departure_bars,
                    atr_value=atr_value,
                )
            )

    # Overlapping base windows often represent the same pause. Keep the strongest/newest
    # interpretation while retaining distinct patterns when price zones do not overlap.
    selected: list[StructuredZone] = []
    for candidate in sorted(
        candidates,
        key=lambda item: (item.research_quality, item.base_end_index, -item.base_candle_count),
        reverse=True,
    ):
        if candidate.zone.broken:
            continue
        if any(_zone_overlap(candidate.zone, other.zone) >= Decimal("0.75") for other in selected):
            continue
        selected.append(candidate)
    return tuple(sorted(selected, key=lambda item: (item.base_start_index, item.pattern.value)))


def _compact_base(
    base: Sequence[Candle],
    *,
    atr_value: Decimal,
    policy: StructuredZoneDetectionPolicy,
) -> bool:
    high = max(item.high for item in base)
    low = min(item.low for item in base)
    if (high - low) / atr_value > policy.maximum_base_width_atr:
        return False
    if any((item.high - item.low) / atr_value > policy.maximum_base_candle_range_atr for item in base):
        return False
    return True


def _arrival(candles: Sequence[Candle], *, atr_value: Decimal) -> tuple[Direction, Decimal]:
    if not candles:
        return Direction.FLAT, Decimal("0")
    start = candles[0].open
    end = candles[-1].close
    move = end - start
    magnitude = abs(move) / atr_value
    if move > 0:
        return Direction.LONG, magnitude
    if move < 0:
        return Direction.SHORT, magnitude
    return Direction.FLAT, Decimal("0")


def _departure(
    base: Sequence[Candle],
    candles: Sequence[Candle],
    *,
    atr_value: Decimal,
) -> tuple[Direction, Decimal, int]:
    base_high = max(item.high for item in base)
    base_low = min(item.low for item in base)
    best_up = Decimal("0")
    best_down = Decimal("0")
    best_up_bar = 1
    best_down_bar = 1
    for index, candle in enumerate(candles, start=1):
        up = max(Decimal("0"), candle.high - base_high) / atr_value
        down = max(Decimal("0"), base_low - candle.low) / atr_value
        if up > best_up:
            best_up = up
            best_up_bar = index
        if down > best_down:
            best_down = down
            best_down_bar = index
    if best_up > best_down:
        return Direction.LONG, best_up, best_up_bar
    if best_down > best_up:
        return Direction.SHORT, best_down, best_down_bar
    return Direction.FLAT, Decimal("0"), 1


def _pattern(arrival: Direction, departure: Direction) -> StructuredZonePattern | None:
    mapping = {
        (Direction.LONG, Direction.LONG): StructuredZonePattern.RALLY_BASE_RALLY,
        (Direction.LONG, Direction.SHORT): StructuredZonePattern.RALLY_BASE_DROP,
        (Direction.SHORT, Direction.LONG): StructuredZonePattern.DROP_BASE_RALLY,
        (Direction.SHORT, Direction.SHORT): StructuredZonePattern.DROP_BASE_DROP,
    }
    return mapping.get((arrival, departure))


def _build_structured_zone(
    candles: Sequence[Candle],
    *,
    base_start: int,
    base_end: int,
    departure_end: int,
    pattern: StructuredZonePattern,
    arrival_atr: Decimal,
    departure_atr: Decimal,
    departure_bars: int,
    atr_value: Decimal,
) -> StructuredZone:
    base = candles[base_start : base_end + 1]
    base_high = max(item.high for item in base)
    base_low = min(item.low for item in base)
    if pattern.kind is ZoneKind.DEMAND:
        distal = base_low
        proximal = max(max(item.open, item.close) for item in base)
    else:
        distal = base_high
        proximal = min(min(item.open, item.close) for item in base)
    low = min(proximal, distal)
    high = max(proximal, distal)
    width = max(high - low, Decimal("0.00000001"))

    touches = 0
    max_penetration = Decimal("0")
    broken = False
    for candle in candles[departure_end + 1 :]:
        if candle.low <= high and candle.high >= low:
            touches += 1
            if pattern.kind is ZoneKind.DEMAND:
                depth = max(Decimal("0"), high - candle.low)
            else:
                depth = max(Decimal("0"), candle.high - low)
            max_penetration = max(max_penetration, min(Decimal("1"), depth / width))
        if pattern.kind is ZoneKind.DEMAND and candle.close < distal:
            broken = True
        if pattern.kind is ZoneKind.SUPPLY and candle.close > distal:
            broken = True

    freshness = Decimal("1") / Decimal(1 + touches)
    body_overlap = _body_overlap(base)
    base_width_atr = (base_high - base_low) / atr_value
    departure_speed = departure_atr / Decimal(max(1, departure_bars))
    imbalance = _imbalance_evidence(candles[base_end : departure_end + 1], atr_value=atr_value)

    # Research-only ranking. Runtime continues using the existing Zone.quality formula.
    quality = (
        min(Decimal("1"), departure_atr / Decimal("3")) * Decimal("0.30")
        + min(Decimal("1"), departure_speed / Decimal("1.5")) * Decimal("0.20")
        + freshness * Decimal("0.20")
        + body_overlap * Decimal("0.15")
        + imbalance * Decimal("0.15")
    )
    quality *= Decimal("1") - max_penetration * Decimal("0.35")
    quality = max(Decimal("0"), min(Decimal("1"), quality))

    identity = (
        f"structured|{pattern.value}|{candles[base_start].time.isoformat()}|"
        f"{candles[base_end].time.isoformat()}|{distal}|{proximal}"
    )
    zone = Zone(
        zone_id=sha256(identity.encode()).hexdigest()[:20],
        kind=pattern.kind,
        proximal=proximal,
        distal=distal,
        origin_index=base_start,
        created_at=candles[base_start].time,
        departure_multiple=departure_atr,
        touches=touches,
        penetration=max_penetration,
        freshness=freshness,
        quality=quality,
        broken=broken,
    )
    return StructuredZone(
        zone=zone,
        pattern=pattern,
        base_start_index=base_start,
        base_end_index=base_end,
        base_candle_count=base_end - base_start + 1,
        arrival_atr=arrival_atr,
        departure_atr=departure_atr,
        departure_bars=departure_bars,
        departure_speed_atr_per_bar=departure_speed,
        base_width_atr=base_width_atr,
        body_overlap=body_overlap,
        imbalance_evidence=imbalance,
        age_bars=max(0, len(candles) - 1 - base_end),
        research_quality=quality,
    )


def _body_overlap(base: Sequence[Candle]) -> Decimal:
    if len(base) == 1:
        return Decimal("1")
    lows = [min(item.open, item.close) for item in base]
    highs = [max(item.open, item.close) for item in base]
    overlap = max(Decimal("0"), min(highs) - max(lows))
    union = max(highs) - min(lows)
    if union <= 0:
        return Decimal("1")
    return max(Decimal("0"), min(Decimal("1"), overlap / union))


def _imbalance_evidence(candles: Sequence[Candle], *, atr_value: Decimal) -> Decimal:
    best = Decimal("0")
    for first, second in zip(candles, candles[1:]):
        if first.high < second.low:
            best = max(best, (second.low - first.high) / atr_value)
        elif first.low > second.high:
            best = max(best, (first.low - second.high) / atr_value)
    return max(Decimal("0"), min(Decimal("1"), best))


def _zone_overlap(first: Zone, second: Zone) -> Decimal:
    overlap = max(Decimal("0"), min(first.high, second.high) - max(first.low, second.low))
    span = max(first.high - first.low, second.high - second.low, Decimal("0.00000001"))
    return overlap / span


def by_pattern(
    zones: Iterable[StructuredZone],
    pattern: StructuredZonePattern,
) -> tuple[StructuredZone, ...]:
    return tuple(item for item in zones if item.pattern is pattern)
