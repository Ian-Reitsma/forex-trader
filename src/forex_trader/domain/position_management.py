from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal
from enum import StrEnum

from forex_trader.domain.enums import Direction


class ManagementAction(StrEnum):
    HOLD = "hold"
    REDUCE = "reduce"
    MOVE_PROTECTION = "move_protection"
    CLOSE = "close"


@dataclass(frozen=True, slots=True)
class PositionManagementContext:
    instrument: str
    direction: Direction
    opened_at: datetime
    observed_at: datetime
    entry_price: Decimal
    current_price: Decimal
    stop_loss: Decimal
    take_profit: Decimal
    upcoming_high_impact_event_at: datetime | None = None
    structure_invalidated: bool = False
    protection_confirmed: bool = True

    def __post_init__(self) -> None:
        if self.opened_at.tzinfo is None or self.observed_at.tzinfo is None:
            raise ValueError("management timestamps must be timezone-aware")
        if self.observed_at < self.opened_at:
            raise ValueError("observed_at cannot precede opened_at")
        if self.upcoming_high_impact_event_at is not None and self.upcoming_high_impact_event_at.tzinfo is None:
            raise ValueError("event time must be timezone-aware")
        if self.direction is Direction.LONG and not self.stop_loss < self.entry_price < self.take_profit:
            raise ValueError("long protection geometry is invalid")
        if self.direction is Direction.SHORT and not self.take_profit < self.entry_price < self.stop_loss:
            raise ValueError("short protection geometry is invalid")

    @property
    def original_risk(self) -> Decimal:
        return abs(self.entry_price - self.stop_loss)

    @property
    def progress_r(self) -> Decimal:
        if self.original_risk <= 0:
            return Decimal("0")
        move = self.current_price - self.entry_price if self.direction is Direction.LONG else self.entry_price - self.current_price
        return move / self.original_risk


@dataclass(frozen=True, slots=True)
class ManagementIntent:
    action: ManagementAction
    reason: str
    reduce_fraction: Decimal = Decimal("0")
    new_stop_loss: Decimal | None = None


@dataclass(frozen=True, slots=True)
class RuntimeManagementPolicy:
    maximum_holding_time: timedelta = timedelta(minutes=120)
    progress_check_after: timedelta = timedelta(minutes=30)
    minimum_progress_r: Decimal = Decimal("0.15")
    close_before_event: timedelta = timedelta(minutes=10)
    reduce_before_event: timedelta = timedelta(minutes=30)
    event_reduce_fraction: Decimal = Decimal("0.5")
    break_even_after_r: Decimal = Decimal("1")

    def __post_init__(self) -> None:
        if self.maximum_holding_time <= timedelta(0) or self.progress_check_after <= timedelta(0):
            raise ValueError("management time windows must be positive")
        if self.minimum_progress_r < 0 or self.break_even_after_r <= 0:
            raise ValueError("management R thresholds are invalid")
        if not Decimal("0") < self.event_reduce_fraction < Decimal("1"):
            raise ValueError("event_reduce_fraction must be in (0,1)")
        if self.close_before_event < timedelta(0) or self.reduce_before_event < self.close_before_event:
            raise ValueError("event windows are invalid")

    def decide(self, context: PositionManagementContext) -> ManagementIntent:
        age = context.observed_at - context.opened_at
        if not context.protection_confirmed:
            return ManagementIntent(ManagementAction.CLOSE, "broker protection is not confirmed")
        if context.structure_invalidated:
            return ManagementIntent(ManagementAction.CLOSE, "original structure has invalidated")
        if age >= self.maximum_holding_time:
            return ManagementIntent(ManagementAction.CLOSE, "maximum scalp holding time reached")
        if age >= self.progress_check_after and context.progress_r < self.minimum_progress_r:
            return ManagementIntent(ManagementAction.CLOSE, f"failure to progress: {context.progress_r:.3f}R")
        if context.upcoming_high_impact_event_at is not None:
            until_event = context.upcoming_high_impact_event_at - context.observed_at
            if timedelta(0) <= until_event <= self.close_before_event:
                return ManagementIntent(ManagementAction.CLOSE, "high-impact event inside close protection window")
            if self.close_before_event < until_event <= self.reduce_before_event and context.progress_r > 0:
                return ManagementIntent(
                    ManagementAction.REDUCE,
                    "reduce profitable exposure before high-impact event",
                    reduce_fraction=self.event_reduce_fraction,
                )
        if context.progress_r >= self.break_even_after_r:
            if context.direction is Direction.LONG and context.stop_loss < context.entry_price:
                return ManagementIntent(ManagementAction.MOVE_PROTECTION, "one-R progress permits structural risk reduction", new_stop_loss=context.entry_price)
            if context.direction is Direction.SHORT and context.stop_loss > context.entry_price:
                return ManagementIntent(ManagementAction.MOVE_PROTECTION, "one-R progress permits structural risk reduction", new_stop_loss=context.entry_price)
        return ManagementIntent(ManagementAction.HOLD, "original thesis remains valid")
