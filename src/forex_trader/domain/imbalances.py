from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from hashlib import sha256

from forex_trader.domain.enums import Direction
from forex_trader.domain.models import Candle


@dataclass(frozen=True, slots=True)
class FairValueGap:
    gap_id: str
    direction: Direction
    lower: Decimal
    upper: Decimal
    left_index: int
    right_index: int
    created_at: object
    width: Decimal
    touched: bool
    fully_mitigated: bool
    fill_fraction: Decimal

    def contains(self, price: Decimal) -> bool:
        return self.lower <= price <= self.upper

    def distance(self, price: Decimal) -> Decimal:
        if self.contains(price):
            return Decimal("0")
        return self.lower - price if price < self.lower else price - self.upper


def detect_fair_value_gaps(
    candles: list[Candle],
    *,
    minimum_gap: Decimal = Decimal("0"),
    lookback: int = 160,
) -> list[FairValueGap]:
    """Detect standard three-candle price imbalances and later mitigation.

    Bullish FVG: candle 3 low is above candle 1 high.
    Bearish FVG: candle 3 high is below candle 1 low.

    This is a descriptive market-location feature. It makes no claim that the gap was
    created by a particular participant class and is not, by itself, a trading signal.
    """
    if minimum_gap < 0:
        raise ValueError("minimum_gap cannot be negative")
    if lookback < 3:
        raise ValueError("lookback must be at least 3")
    completed = [candle for candle in candles if candle.complete]
    if len(completed) < 3:
        return []
    start = max(0, len(completed) - lookback)
    gaps: list[FairValueGap] = []
    for right_index in range(max(2, start + 2), len(completed)):
        left_index = right_index - 2
        left = completed[left_index]
        right = completed[right_index]
        if right.low - left.high >= minimum_gap and right.low > left.high:
            gaps.append(
                _build_gap(
                    completed,
                    direction=Direction.LONG,
                    lower=left.high,
                    upper=right.low,
                    left_index=left_index,
                    right_index=right_index,
                )
            )
        if left.low - right.high >= minimum_gap and right.high < left.low:
            gaps.append(
                _build_gap(
                    completed,
                    direction=Direction.SHORT,
                    lower=right.high,
                    upper=left.low,
                    left_index=left_index,
                    right_index=right_index,
                )
            )
    return gaps


def nearest_open_fvg(
    gaps: list[FairValueGap],
    *,
    direction: Direction,
    price: Decimal,
    maximum_distance: Decimal,
) -> FairValueGap | None:
    if maximum_distance < 0:
        raise ValueError("maximum_distance cannot be negative")
    eligible = [
        gap
        for gap in gaps
        if gap.direction is direction
        and not gap.fully_mitigated
        and gap.distance(price) <= maximum_distance
    ]
    if not eligible:
        return None
    return min(
        eligible,
        key=lambda gap: (gap.distance(price), gap.fill_fraction, -gap.right_index),
    )


def fvg_zone_overlap_fraction(gap: FairValueGap, *, zone_low: Decimal, zone_high: Decimal) -> Decimal:
    """Return 0..1 overlap of an FVG with an independently derived price zone."""
    low, high = min(zone_low, zone_high), max(zone_low, zone_high)
    overlap = max(Decimal("0"), min(gap.upper, high) - max(gap.lower, low))
    return min(Decimal("1"), overlap / max(gap.width, Decimal("0.0000000001")))


def _build_gap(
    candles: list[Candle],
    *,
    direction: Direction,
    lower: Decimal,
    upper: Decimal,
    left_index: int,
    right_index: int,
) -> FairValueGap:
    width = upper - lower
    touched = False
    fully_mitigated = False
    fill_fraction = Decimal("0")
    for candle in candles[right_index + 1 :]:
        if direction is Direction.LONG:
            if candle.low <= upper:
                touched = True
                penetration = upper - max(lower, candle.low)
                fill_fraction = max(fill_fraction, min(Decimal("1"), penetration / width))
            if candle.low <= lower:
                fully_mitigated = True
                fill_fraction = Decimal("1")
                break
        else:
            if candle.high >= lower:
                touched = True
                penetration = min(upper, candle.high) - lower
                fill_fraction = max(fill_fraction, min(Decimal("1"), penetration / width))
            if candle.high >= upper:
                fully_mitigated = True
                fill_fraction = Decimal("1")
                break
    created_at = candles[right_index].time
    raw = f"{direction.value}|{created_at.isoformat()}|{lower}|{upper}"
    return FairValueGap(
        gap_id=sha256(raw.encode()).hexdigest()[:20],
        direction=direction,
        lower=lower,
        upper=upper,
        left_index=left_index,
        right_index=right_index,
        created_at=created_at,
        width=width,
        touched=touched,
        fully_mitigated=fully_mitigated,
        fill_fraction=fill_fraction,
    )
