from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from enum import StrEnum
from typing import Iterable
from uuid import UUID, uuid4

from forex_trader.domain.fundamentals import FundamentalBook
from forex_trader.domain.models import CurrencyFundamentals, FundamentalAssessment


class MacroObservationKind(StrEnum):
    RELEASE = "release"
    NEWS = "news"
    CENTRAL_BANK = "central_bank"


@dataclass(frozen=True, slots=True)
class MacroObservation:
    observation_id: UUID
    kind: MacroObservationKind
    currency: str
    available_at: datetime
    source: str = "manual"
    category: str = ""
    actual: Decimal | None = None
    forecast: Decimal | None = None
    previous: Decimal | None = None
    higher_is_positive: bool = True
    importance: Decimal = Decimal("1")
    headline: str = ""
    body: str = ""
    source_weight: Decimal = Decimal("0.7")
    revision_of: UUID | None = None

    def __post_init__(self) -> None:
        if self.available_at.tzinfo is None:
            raise ValueError("available_at must be timezone-aware")
        if len(self.currency.strip()) != 3:
            raise ValueError("currency must be a three-letter code")
        if self.kind is MacroObservationKind.RELEASE:
            if self.actual is None or self.forecast is None or self.previous is None:
                raise ValueError("release observations require actual, forecast, and previous")

    @classmethod
    def release(
        cls,
        *,
        currency: str,
        category: str,
        actual: Decimal,
        forecast: Decimal,
        previous: Decimal,
        higher_is_positive: bool,
        importance: Decimal = Decimal("1"),
        available_at: datetime | None = None,
        source: str = "manual",
        revision_of: UUID | None = None,
    ) -> "MacroObservation":
        return cls(
            observation_id=uuid4(),
            kind=MacroObservationKind.RELEASE,
            currency=currency.upper(),
            category=category,
            actual=actual,
            forecast=forecast,
            previous=previous,
            higher_is_positive=higher_is_positive,
            importance=importance,
            available_at=available_at or datetime.now(UTC),
            source=source,
            revision_of=revision_of,
        )

    @classmethod
    def news(
        cls,
        *,
        currency: str,
        headline: str,
        body: str = "",
        source_weight: Decimal = Decimal("0.7"),
        available_at: datetime | None = None,
        source: str = "manual",
        kind: MacroObservationKind = MacroObservationKind.NEWS,
    ) -> "MacroObservation":
        return cls(
            observation_id=uuid4(),
            kind=kind,
            currency=currency.upper(),
            headline=headline,
            body=body,
            source_weight=source_weight,
            available_at=available_at or datetime.now(UTC),
            source=source,
        )


class PointInTimeFundamentalBook:
    """Reconstructs fundamental state using only observations available by `as_of`."""

    def __init__(
        self,
        observations: Iterable[MacroObservation] | None = None,
        *,
        seeds: Iterable[CurrencyFundamentals] | None = None,
    ) -> None:
        self._observations = sorted(
            list(observations or []), key=lambda item: (item.available_at, str(item.observation_id))
        )
        self._seeds = list(seeds or [])

    def append(self, observation: MacroObservation) -> None:
        self._observations.append(observation)
        self._observations.sort(key=lambda item: (item.available_at, str(item.observation_id)))

    def observations(self, *, as_of: datetime | None = None) -> list[MacroObservation]:
        if as_of is None:
            return list(self._observations)
        if as_of.tzinfo is None:
            raise ValueError("as_of must be timezone-aware")
        return [item for item in self._observations if item.available_at <= as_of]

    def book_at(self, as_of: datetime) -> FundamentalBook:
        if as_of.tzinfo is None:
            raise ValueError("as_of must be timezone-aware")
        eligible_seeds = [seed for seed in self._seeds if seed.as_of <= as_of]
        book = FundamentalBook(eligible_seeds)
        for observation in self._observations:
            if observation.available_at > as_of:
                break
            if observation.kind is MacroObservationKind.RELEASE:
                assert observation.actual is not None
                assert observation.forecast is not None
                assert observation.previous is not None
                book.apply_release(
                    currency=observation.currency,
                    category=observation.category,
                    actual=observation.actual,
                    forecast=observation.forecast,
                    previous=observation.previous,
                    higher_is_positive=observation.higher_is_positive,
                    importance=observation.importance,
                    observed_at=observation.available_at,
                )
            else:
                book.apply_news(
                    currency=observation.currency,
                    headline=observation.headline,
                    body=observation.body,
                    source_weight=observation.source_weight,
                    observed_at=observation.available_at,
                )
        return book

    def assess_pair(
        self,
        instrument: str,
        *,
        as_of: datetime | None = None,
        maximum_age: timedelta = timedelta(days=7),
    ) -> FundamentalAssessment:
        observed_at = as_of or datetime.now(UTC)
        return self.book_at(observed_at).assess_pair(
            instrument,
            as_of=observed_at,
            maximum_age=maximum_age,
        )
