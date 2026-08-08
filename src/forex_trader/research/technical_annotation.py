from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from datetime import datetime
from decimal import Decimal
from enum import StrEnum
from typing import Iterable, Mapping

from forex_trader.domain.models import Candle


TECHNICAL_ANNOTATION_POLICY_VERSION = "technical-annotation-v1"


class BinaryTechnicalLabel(StrEnum):
    PRESENT = "present"
    ABSENT = "absent"
    AMBIGUOUS = "ambiguous"


class TechnicalDirectionLabel(StrEnum):
    LONG = "long"
    SHORT = "short"
    NONE = "none"
    AMBIGUOUS = "ambiguous"


@dataclass(frozen=True, slots=True)
class TechnicalGroundTruthLabel:
    zone: BinaryTechnicalLabel
    liquidity_sweep: BinaryTechnicalLabel
    structure_shift: BinaryTechnicalLabel
    retest: BinaryTechnicalLabel
    direction: TechnicalDirectionLabel


@dataclass(frozen=True, slots=True)
class TechnicalWindow:
    instrument: str
    timeframe: str
    candles: tuple[Candle, ...]

    def __post_init__(self) -> None:
        if not self.instrument.strip():
            raise ValueError("technical window instrument is required")
        if not self.timeframe.strip():
            raise ValueError("technical window timeframe is required")
        if len(self.candles) < 8:
            raise ValueError("technical annotation windows require at least 8 candles")
        ordered = tuple(sorted(self.candles, key=lambda item: item.time))
        if ordered != self.candles:
            raise ValueError("technical annotation candles must be chronologically ordered")
        if any(not candle.complete for candle in self.candles):
            raise ValueError("technical annotation windows may contain completed candles only")
        if len({candle.time for candle in self.candles}) != len(self.candles):
            raise ValueError("technical annotation candle timestamps must be unique")


@dataclass(frozen=True, slots=True)
class TechnicalAnnotationPacket:
    packet_id: str
    instrument: str
    timeframe: str
    window_start: datetime
    window_end: datetime
    candle_hash: str
    candles: tuple[Candle, ...]

    def __post_init__(self) -> None:
        if self.window_start.tzinfo is None or self.window_end.tzinfo is None:
            raise ValueError("technical annotation packet times must be timezone-aware")
        if self.window_end < self.window_start:
            raise ValueError("technical annotation window_end precedes window_start")

    def public_payload(self) -> dict[str, object]:
        """Return reviewer-visible data without model predictions or trade outcomes."""

        return {
            "packet_id": self.packet_id,
            "instrument": self.instrument,
            "timeframe": self.timeframe,
            "window_start": self.window_start.isoformat(),
            "window_end": self.window_end.isoformat(),
            "candle_hash": self.candle_hash,
            "candles": [_candle_payload(candle) for candle in self.candles],
        }


@dataclass(frozen=True, slots=True)
class TechnicalAnnotationBatch:
    batch_id: str
    policy_version: str
    frozen_as_of: datetime
    packets: tuple[TechnicalAnnotationPacket, ...]

    def __post_init__(self) -> None:
        if self.frozen_as_of.tzinfo is None:
            raise ValueError("technical annotation frozen_as_of must be timezone-aware")
        if not self.packets:
            raise ValueError("technical annotation batch must contain packets")
        if len({packet.packet_id for packet in self.packets}) != len(self.packets):
            raise ValueError("technical annotation packet IDs must be unique")

    def public_payload(self) -> dict[str, object]:
        return {
            "schema_version": "1.0",
            "batch_id": self.batch_id,
            "policy_version": self.policy_version,
            "frozen_as_of": self.frozen_as_of.isoformat(),
            "packets": [packet.public_payload() for packet in self.packets],
        }


@dataclass(frozen=True, slots=True)
class TechnicalHoldoutManifest:
    batch_id: str
    policy_version: str
    frozen_as_of: datetime
    calibration_packet_ids: tuple[str, ...]
    holdout_packet_ids: tuple[str, ...]
    manifest_hash: str


@dataclass(frozen=True, slots=True)
class TechnicalReviewerSubmission:
    packet_id: str
    reviewer_id: str
    label: TechnicalGroundTruthLabel

    def __post_init__(self) -> None:
        if not self.packet_id.strip() or not self.reviewer_id.strip():
            raise ValueError("reviewer submission requires packet_id and reviewer_id")


@dataclass(frozen=True, slots=True)
class TechnicalAdjudication:
    packet_id: str
    adjudicator_id: str
    label: TechnicalGroundTruthLabel

    def __post_init__(self) -> None:
        if not self.packet_id.strip() or not self.adjudicator_id.strip():
            raise ValueError("technical adjudication requires packet_id and adjudicator_id")


@dataclass(frozen=True, slots=True)
class FinalTechnicalLabel:
    packet_id: str
    label: TechnicalGroundTruthLabel
    reviewer_ids: tuple[str, ...]
    agreement: bool
    adjudicator_id: str | None = None


@dataclass(frozen=True, slots=True)
class TechnicalValidationCorpus:
    batch_id: str
    policy_version: str
    labels: tuple[FinalTechnicalLabel, ...]


def build_blinded_technical_batch(
    windows: Iterable[TechnicalWindow],
    *,
    frozen_as_of: datetime,
    policy_version: str = TECHNICAL_ANNOTATION_POLICY_VERSION,
) -> TechnicalAnnotationBatch:
    if frozen_as_of.tzinfo is None:
        raise ValueError("frozen_as_of must be timezone-aware")
    packets: list[TechnicalAnnotationPacket] = []
    for window in windows:
        if window.candles[-1].time > frozen_as_of:
            raise ValueError("technical annotation window contains candles after frozen_as_of")
        candle_payload = [_candle_payload(candle) for candle in window.candles]
        serialized = json.dumps(candle_payload, sort_keys=True, separators=(",", ":"))
        candle_hash = hashlib.sha256(serialized.encode()).hexdigest()
        identity = "|".join(
            (
                window.instrument.upper(),
                window.timeframe.upper(),
                window.candles[0].time.isoformat(),
                window.candles[-1].time.isoformat(),
                candle_hash,
                policy_version,
            )
        )
        packet_id = f"tech-{hashlib.sha256(identity.encode()).hexdigest()[:24]}"
        packets.append(
            TechnicalAnnotationPacket(
                packet_id=packet_id,
                instrument=window.instrument.upper(),
                timeframe=window.timeframe.upper(),
                window_start=window.candles[0].time,
                window_end=window.candles[-1].time,
                candle_hash=candle_hash,
                candles=window.candles,
            )
        )
    ordered = tuple(
        sorted(
            packets,
            key=lambda item: (item.window_end, item.instrument, item.timeframe, item.packet_id),
        )
    )
    if not ordered:
        raise ValueError("cannot build an empty technical annotation batch")
    batch_identity = "|".join(
        (
            policy_version,
            frozen_as_of.isoformat(),
            *(packet.packet_id for packet in ordered),
        )
    )
    batch_id = f"technical-batch-{hashlib.sha256(batch_identity.encode()).hexdigest()[:24]}"
    return TechnicalAnnotationBatch(batch_id, policy_version, frozen_as_of, ordered)


def split_technical_calibration_holdout(batch: TechnicalAnnotationBatch) -> TechnicalHoldoutManifest:
    """Chronologically split one frozen batch using a non-tunable 2/3 : 1/3 rule."""

    if len(batch.packets) < 3:
        raise ValueError("technical holdout requires at least 3 packets")
    calibration_count = (len(batch.packets) * 2) // 3
    if calibration_count < 1 or calibration_count >= len(batch.packets):
        raise ValueError("technical holdout split would create an empty partition")
    calibration = tuple(packet.packet_id for packet in batch.packets[:calibration_count])
    holdout = tuple(packet.packet_id for packet in batch.packets[calibration_count:])
    canonical = {
        "batch_id": batch.batch_id,
        "policy_version": batch.policy_version,
        "frozen_as_of": batch.frozen_as_of.isoformat(),
        "calibration_packet_ids": calibration,
        "holdout_packet_ids": holdout,
    }
    digest = hashlib.sha256(
        json.dumps(canonical, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    return TechnicalHoldoutManifest(
        batch.batch_id,
        batch.policy_version,
        batch.frozen_as_of,
        calibration,
        holdout,
        digest,
    )


def finalize_technical_labels(
    batch: TechnicalAnnotationBatch,
    submissions: Iterable[TechnicalReviewerSubmission],
    adjudications: Iterable[TechnicalAdjudication] = (),
    *,
    required_packet_ids: Iterable[str] | None = None,
    minimum_reviewers: int = 2,
) -> TechnicalValidationCorpus:
    if minimum_reviewers < 2:
        raise ValueError("technical ground truth requires at least two independent reviewers")
    packet_ids = {packet.packet_id for packet in batch.packets}
    required = set(packet_ids if required_packet_ids is None else required_packet_ids)
    if not required <= packet_ids:
        unknown = ", ".join(sorted(required - packet_ids))
        raise ValueError(f"required packet IDs are not in batch: {unknown}")

    grouped: dict[str, dict[str, TechnicalReviewerSubmission]] = {}
    for submission in submissions:
        if submission.packet_id not in packet_ids:
            raise ValueError(f"review submission references unknown packet {submission.packet_id}")
        by_reviewer = grouped.setdefault(submission.packet_id, {})
        if submission.reviewer_id in by_reviewer:
            raise ValueError(
                f"duplicate reviewer submission for {submission.packet_id}:{submission.reviewer_id}"
            )
        by_reviewer[submission.reviewer_id] = submission

    adjudication_map: dict[str, TechnicalAdjudication] = {}
    for adjudication in adjudications:
        if adjudication.packet_id not in packet_ids:
            raise ValueError(f"adjudication references unknown packet {adjudication.packet_id}")
        if adjudication.packet_id in adjudication_map:
            raise ValueError(f"duplicate adjudication for {adjudication.packet_id}")
        adjudication_map[adjudication.packet_id] = adjudication

    finalized: list[FinalTechnicalLabel] = []
    for packet in batch.packets:
        if packet.packet_id not in required:
            continue
        reviews = grouped.get(packet.packet_id, {})
        if len(reviews) < minimum_reviewers:
            raise ValueError(
                f"packet {packet.packet_id} has {len(reviews)} reviewers; {minimum_reviewers} required"
            )
        reviewer_ids = tuple(sorted(reviews))
        labels = [reviews[reviewer_id].label for reviewer_id in reviewer_ids]
        first = labels[0]
        agreement = all(label == first for label in labels[1:])
        if agreement:
            if packet.packet_id in adjudication_map:
                unanimous_adjudication = adjudication_map[packet.packet_id]
                if unanimous_adjudication.adjudicator_id in reviews:
                    raise ValueError("adjudicator must be independent from packet reviewers")
                if unanimous_adjudication.label != first:
                    raise ValueError("unnecessary adjudication contradicts unanimous reviewer labels")
            finalized.append(FinalTechnicalLabel(packet.packet_id, first, reviewer_ids, True))
            continue
        required_adjudication = adjudication_map.get(packet.packet_id)
        if required_adjudication is None:
            raise ValueError(f"packet {packet.packet_id} has reviewer disagreement and requires adjudication")
        if required_adjudication.adjudicator_id in reviews:
            raise ValueError("adjudicator must be independent from packet reviewers")
        finalized.append(
            FinalTechnicalLabel(
                packet.packet_id,
                required_adjudication.label,
                reviewer_ids,
                False,
                required_adjudication.adjudicator_id,
            )
        )
    return TechnicalValidationCorpus(batch.batch_id, batch.policy_version, tuple(finalized))


def technical_batch_from_payload(payload: Mapping[str, object]) -> TechnicalAnnotationBatch:
    if str(payload.get("schema_version")) != "1.0":
        raise ValueError("unsupported technical annotation schema_version")
    frozen_as_of = _aware(str(payload["frozen_as_of"]))
    packets_payload = payload.get("packets")
    if not isinstance(packets_payload, list):
        raise ValueError("technical annotation packets must be a list")
    packets: list[TechnicalAnnotationPacket] = []
    for raw_packet in packets_payload:
        if not isinstance(raw_packet, dict):
            raise ValueError("technical annotation packet must be an object")
        raw_candles = raw_packet.get("candles")
        if not isinstance(raw_candles, list):
            raise ValueError("technical annotation packet candles must be a list")
        candles = tuple(_candle_from_payload(item) for item in raw_candles)
        packet = TechnicalAnnotationPacket(
            packet_id=str(raw_packet["packet_id"]),
            instrument=str(raw_packet["instrument"]).upper(),
            timeframe=str(raw_packet["timeframe"]).upper(),
            window_start=_aware(str(raw_packet["window_start"])),
            window_end=_aware(str(raw_packet["window_end"])),
            candle_hash=str(raw_packet["candle_hash"]),
            candles=candles,
        )
        expected_hash = hashlib.sha256(
            json.dumps(
                [_candle_payload(candle) for candle in candles],
                sort_keys=True,
                separators=(",", ":"),
            ).encode()
        ).hexdigest()
        if expected_hash != packet.candle_hash:
            raise ValueError(f"technical annotation candle hash mismatch for {packet.packet_id}")
        packets.append(packet)
    return TechnicalAnnotationBatch(
        batch_id=str(payload["batch_id"]),
        policy_version=str(payload["policy_version"]),
        frozen_as_of=frozen_as_of,
        packets=tuple(packets),
    )


def label_payload(label: TechnicalGroundTruthLabel) -> dict[str, str]:
    return {key: str(value) for key, value in asdict(label).items()}


def _aware(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("timestamp must be timezone-aware")
    return parsed


def _candle_payload(candle: Candle) -> dict[str, object]:
    return {
        "time": candle.time.isoformat(),
        "open": str(candle.open),
        "high": str(candle.high),
        "low": str(candle.low),
        "close": str(candle.close),
        "volume": candle.volume,
        "complete": candle.complete,
    }


def _candle_from_payload(payload: object) -> Candle:
    if not isinstance(payload, dict):
        raise ValueError("candle payload must be an object")
    return Candle(
        time=_aware(str(payload["time"])),
        open=Decimal(str(payload["open"])),
        high=Decimal(str(payload["high"])),
        low=Decimal(str(payload["low"])),
        close=Decimal(str(payload["close"])),
        volume=int(payload.get("volume", 0)),
        complete=bool(payload.get("complete", True)),
    )
