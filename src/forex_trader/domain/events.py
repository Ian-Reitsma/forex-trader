from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal
from enum import StrEnum
from uuid import UUID, uuid4

from forex_trader.domain.market_calendar import pair_holiday_blackout


class EventImportance(StrEnum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


@dataclass(frozen=True, slots=True)
class ScheduledMacroEvent:
    event_id: UUID
    currency: str
    scheduled_at: datetime
    name: str
    importance: EventImportance = EventImportance.HIGH
    source: str = "manual"
    pre_blackout: timedelta = timedelta(minutes=15)
    post_blackout: timedelta = timedelta(minutes=5)
    confidence: Decimal = Decimal("1")

    def __post_init__(self) -> None:
        if self.scheduled_at.tzinfo is None:
            raise ValueError("scheduled_at must be timezone-aware")
        if len(self.currency.strip()) != 3:
            raise ValueError("currency must be a three-letter code")
        if self.pre_blackout < timedelta(0) or self.post_blackout < timedelta(0):
            raise ValueError("event blackout windows must be non-negative")

    @classmethod
    def create(
        cls,
        *,
        currency: str,
        scheduled_at: datetime,
        name: str,
        importance: EventImportance = EventImportance.HIGH,
        source: str = "manual",
        pre_blackout: timedelta = timedelta(minutes=15),
        post_blackout: timedelta = timedelta(minutes=5),
        confidence: Decimal = Decimal("1"),
    ) -> "ScheduledMacroEvent":
        return cls(
            event_id=uuid4(),
            currency=currency.upper(),
            scheduled_at=scheduled_at,
            name=name,
            importance=importance,
            source=source,
            pre_blackout=pre_blackout,
            post_blackout=post_blackout,
            confidence=confidence,
        )

    def blocks(self, instant: datetime) -> bool:
        if instant.tzinfo is None:
            raise ValueError("instant must be timezone-aware")
        if self.importance is not EventImportance.HIGH:
            return False
        return self.scheduled_at - self.pre_blackout <= instant <= self.scheduled_at + self.post_blackout


def pair_event_blackout(
    instrument: str,
    instant: datetime,
    events: list[ScheduledMacroEvent],
) -> tuple[bool, tuple[str, ...]]:
    """Block new risk around high-impact releases or currency-market holidays.

    The engine calls this same function during initial evaluation and immediately before
    broker submission, so the context gate cannot be bypassed by a stale pre-event signal.
    Holiday reasons are explicitly labeled to distinguish them from scheduled releases.
    """
    base, quote = instrument.upper().split("_", maxsplit=1)
    blocking = [
        event
        for event in events
        if event.currency in {base, quote} and event.blocks(instant)
    ]
    event_reasons = tuple(
        f"{event.currency} high-impact event '{event.name}' at {event.scheduled_at.isoformat()}"
        for event in sorted(blocking, key=lambda item: item.scheduled_at)
    )
    holiday_blocked, holiday_reasons = pair_holiday_blackout(instrument, instant)
    tagged_holidays = tuple(f"MARKET_HOLIDAY: {reason}" for reason in holiday_reasons)
    reasons = (*event_reasons, *tagged_holidays)
    return bool(blocking) or holiday_blocked, reasons
