from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal
from enum import StrEnum
from uuid import UUID, uuid4


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
    base, quote = instrument.upper().split("_", maxsplit=1)
    blocking = [
        event
        for event in events
        if event.currency in {base, quote} and event.blocks(instant)
    ]
    if not blocking:
        return False, ()
    reasons = tuple(
        f"{event.currency} high-impact event '{event.name}' at {event.scheduled_at.isoformat()}"
        for event in sorted(blocking, key=lambda item: item.scheduled_at)
    )
    return True, reasons
