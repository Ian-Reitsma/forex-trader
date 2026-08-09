from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Iterable
from uuid import NAMESPACE_URL, uuid5

from forex_trader.domain.macro_history import MacroObservation
from forex_trader.intelligence.events import (
    ConsensusSnapshot,
    ReleaseActual,
    ReleaseMetadata,
    ReleaseSurprise,
    calculate_release_surprise,
)

ReleaseKey = tuple[str, str]


def _key(currency: str, indicator: str) -> ReleaseKey:
    return currency.upper(), indicator.strip()


@dataclass(frozen=True, slots=True)
class HistoricalReleaseSurprise:
    metadata: ReleaseMetadata
    consensus: ConsensusSnapshot
    actual: ReleaseActual
    surprise: ReleaseSurprise
    consensus_age: timedelta
    prior_same_indicator_samples: int

    def __post_init__(self) -> None:
        if self.consensus.available_at >= self.actual.available_at:
            raise ValueError("historical consensus must be strictly available before the release actual")
        if self.consensus_age <= timedelta(0):
            raise ValueError("consensus age must be positive")
        if self.prior_same_indicator_samples < 0:
            raise ValueError("prior sample count cannot be negative")

    @property
    def key(self) -> ReleaseKey:
        return _key(self.actual.currency, self.actual.indicator)

    def to_macro_observation(self) -> MacroObservation:
        """Convert the PIT event into the existing fundamental history contract.

        ``forecast`` is the last genuinely pre-release consensus. ``previous`` uses the
        revised previous value because that revision becomes knowable with the actual and
        is therefore legitimate at ``actual.available_at``. The separate ReleaseSurprise
        retains the market-known previous value and explicit revision effect for research.
        """

        identity = (
            f"release:{self.actual.currency.upper()}:{self.actual.indicator}:"
            f"{self.actual.available_at.isoformat()}:{self.consensus.available_at.isoformat()}:"
            f"{self.actual.source}:{self.consensus.source}"
        )
        return MacroObservation.release(
            currency=self.actual.currency,
            category=self.actual.indicator,
            actual=self.actual.actual,
            forecast=self.consensus.consensus,
            previous=self.actual.revised_previous,
            higher_is_positive=self.metadata.directionality > 0,
            available_at=self.actual.available_at,
            source=f"actual={self.actual.source}|consensus={self.consensus.source}",
            observation_id=uuid5(NAMESPACE_URL, identity),
        )


@dataclass(frozen=True, slots=True)
class UnmatchedReleaseActual:
    actual: ReleaseActual
    reason: str


@dataclass(frozen=True, slots=True)
class ReleaseSurpriseHistoryReport:
    records: tuple[HistoricalReleaseSurprise, ...]
    unmatched_actuals: tuple[UnmatchedReleaseActual, ...]

    @property
    def complete(self) -> bool:
        return not self.unmatched_actuals

    def macro_observations(self) -> tuple[MacroObservation, ...]:
        return tuple(item.to_macro_observation() for item in self.records)


class PointInTimeReleaseSurpriseAssembler:
    """Join vendor consensus and release actuals without post-release leakage.

    The assembler is source-agnostic: it does not manufacture consensus from official
    actual data. For each actual it selects the latest same-indicator/currency consensus
    with ``available_at < actual.available_at``. Consensus snapshots stamped at the exact
    actual time are rejected because their ordering relative to the release is ambiguous.

    Surprise normalization is sequential. Only raw surprises from strictly earlier
    releases of the same indicator/currency are passed to ``calculate_release_surprise``.
    A future release can therefore never change an earlier normalized surprise.
    """

    def __init__(
        self,
        metadata: Iterable[ReleaseMetadata],
        consensus: Iterable[ConsensusSnapshot],
        actuals: Iterable[ReleaseActual],
        *,
        maximum_consensus_age: timedelta = timedelta(days=7),
    ) -> None:
        if maximum_consensus_age <= timedelta(0):
            raise ValueError("maximum_consensus_age must be positive")
        self.maximum_consensus_age = maximum_consensus_age
        self._metadata = self._metadata_by_key(metadata)
        self._consensus = tuple(
            sorted(consensus, key=lambda item: (item.available_at, item.currency.upper(), item.indicator, item.source))
        )
        self._actuals = tuple(
            sorted(actuals, key=lambda item: (item.available_at, item.currency.upper(), item.indicator, item.source))
        )

    @staticmethod
    def _metadata_by_key(metadata: Iterable[ReleaseMetadata]) -> dict[ReleaseKey, ReleaseMetadata]:
        result: dict[ReleaseKey, ReleaseMetadata] = {}
        for item in metadata:
            key = _key(item.currency, item.indicator)
            if key in result:
                raise ValueError(f"duplicate release metadata for {key[0]} {key[1]}")
            result[key] = item
        return result

    def assemble(
        self,
        *,
        as_of: datetime | None = None,
        require_complete: bool = False,
    ) -> ReleaseSurpriseHistoryReport:
        if as_of is not None and as_of.tzinfo is None:
            raise ValueError("as_of must be timezone-aware")
        records: list[HistoricalReleaseSurprise] = []
        unmatched: list[UnmatchedReleaseActual] = []
        raw_history: dict[ReleaseKey, list[Decimal]] = {}

        for actual in self._actuals:
            if as_of is not None and actual.available_at > as_of:
                continue
            key = _key(actual.currency, actual.indicator)
            metadata = self._metadata.get(key)
            if metadata is None:
                unmatched.append(UnmatchedReleaseActual(actual, "missing release metadata"))
                continue
            eligible = [
                item
                for item in self._consensus
                if _key(item.currency, item.indicator) == key
                and item.available_at < actual.available_at
                and (as_of is None or item.available_at <= as_of)
            ]
            if not eligible:
                unmatched.append(UnmatchedReleaseActual(actual, "no strictly pre-release consensus snapshot"))
                continue
            selected = max(eligible, key=lambda item: (item.available_at, item.source))
            age = actual.available_at - selected.available_at
            if age > self.maximum_consensus_age:
                unmatched.append(
                    UnmatchedReleaseActual(
                        actual,
                        f"latest pre-release consensus is stale ({age.total_seconds():.0f}s)",
                    )
                )
                continue

            prior = tuple(raw_history.get(key, ()))
            surprise = calculate_release_surprise(
                metadata,
                selected,
                actual,
                historical_raw_surprises=prior,
            )
            record = HistoricalReleaseSurprise(
                metadata=metadata,
                consensus=selected,
                actual=actual,
                surprise=surprise,
                consensus_age=age,
                prior_same_indicator_samples=len(prior),
            )
            records.append(record)
            raw_history.setdefault(key, []).append(surprise.raw_surprise)

        report = ReleaseSurpriseHistoryReport(tuple(records), tuple(unmatched))
        if require_complete and not report.complete:
            summary = "; ".join(
                f"{item.actual.currency.upper()} {item.actual.indicator} @ {item.actual.available_at.isoformat()}: {item.reason}"
                for item in report.unmatched_actuals[:8]
            )
            raise ValueError(f"release surprise history is incomplete: {summary}")
        return report
