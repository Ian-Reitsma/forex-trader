from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from enum import StrEnum

from forex_trader.domain.enums import Direction


class SetupState(StrEnum):
    OBSERVE = "observe"
    LOCATION_IDENTIFIED = "location_identified"
    LIQUIDITY_DEFINED = "liquidity_defined"
    ARMED = "armed"
    LIQUIDITY_TAKEN = "liquidity_taken"
    STRUCTURE_SHIFT_CONFIRMED = "structure_shift_confirmed"
    RETEST_PENDING = "retest_pending"
    ENTRY_CONFIRMED = "entry_confirmed"
    INVALIDATED = "invalidated"
    EXPIRED = "expired"


@dataclass(frozen=True, slots=True)
class SetupContext:
    state: SetupState
    instrument: str
    direction: Direction
    setup_family: str
    signal_time: datetime
    zone_id: str | None = None
    zone_quality: Decimal = Decimal("0")
    liquidity_kind: str | None = None
    liquidity_price: Decimal | None = None
    liquidity_strength: Decimal = Decimal("0")
    sweep_index: int | None = None
    structure_shift: bool = False
    retest_confirmed: bool = False
    location_score: Decimal = Decimal("0")
    reasons: tuple[str, ...] = ()

    @property
    def entry_ready(self) -> bool:
        return self.state is SetupState.ENTRY_CONFIRMED


def derive_setup_state(
    *,
    instrument: str,
    direction: Direction,
    signal_time: datetime,
    zone_id: str | None,
    zone_quality: Decimal,
    liquidity_kind: str | None,
    liquidity_price: Decimal | None,
    liquidity_strength: Decimal,
    sweep_index: int | None,
    latest_index: int,
    structure_shift: bool,
    retest_confirmed: bool,
    location_score: Decimal,
    invalidated: bool = False,
) -> SetupContext:
    reasons: list[str] = []
    state = SetupState.OBSERVE
    if direction is Direction.FLAT:
        reasons.append("no directional higher-timeframe context")
    if zone_id is not None:
        state = SetupState.LOCATION_IDENTIFIED
        reasons.append(f"quality location identified ({zone_quality:.2f})")
    if liquidity_price is not None:
        state = SetupState.LIQUIDITY_DEFINED
        reasons.append(f"declared liquidity={liquidity_kind}@{liquidity_price}")
    if zone_id is not None and liquidity_price is not None and direction is not Direction.FLAT:
        state = SetupState.ARMED
    if sweep_index is not None:
        state = SetupState.LIQUIDITY_TAKEN
        reasons.append("declared liquidity was swept and reclaimed")
    if sweep_index is not None and structure_shift:
        state = SetupState.STRUCTURE_SHIFT_CONFIRMED
        reasons.append("post-sweep structure shift confirmed")
    if sweep_index is not None and structure_shift and latest_index > sweep_index:
        state = SetupState.RETEST_PENDING
    if sweep_index is not None and structure_shift and retest_confirmed:
        state = SetupState.ENTRY_CONFIRMED
        reasons.append("post-shift retest/continuation entry confirmed")
    if invalidated:
        state = SetupState.INVALIDATED
        reasons.append("location was invalidated")
    return SetupContext(
        state=state,
        instrument=instrument,
        direction=direction,
        setup_family="zone_liquidity_sweep_reclaim",
        signal_time=signal_time,
        zone_id=zone_id,
        zone_quality=zone_quality,
        liquidity_kind=liquidity_kind,
        liquidity_price=liquidity_price,
        liquidity_strength=liquidity_strength,
        sweep_index=sweep_index,
        structure_shift=structure_shift,
        retest_confirmed=retest_confirmed,
        location_score=location_score,
        reasons=tuple(reasons),
    )
