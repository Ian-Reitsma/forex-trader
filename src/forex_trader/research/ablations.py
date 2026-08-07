from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from datetime import datetime
from decimal import Decimal
from enum import StrEnum
from pathlib import Path
from typing import Callable, Iterable, Mapping


class AblationVariant(StrEnum):
    FULL = "full"
    NO_FUNDAMENTALS = "no_fundamentals"
    NO_FLOW = "no_flow"
    NO_SESSION = "no_session"
    NO_ZONE_QUALITY = "no_zone_quality"
    NO_RETEST = "no_retest"


REQUIRED_ABLATION_VARIANTS: tuple[AblationVariant, ...] = tuple(AblationVariant)


@dataclass(frozen=True, slots=True)
class FrozenAblationSnapshot:
    """Immutable point-in-time identity shared by every prospective variant evaluation."""

    snapshot_id: str
    instrument: str
    signal_time: datetime
    policy_fingerprint: str
    payload_hash: str

    def __post_init__(self) -> None:
        if not self.snapshot_id.strip() or not self.instrument.strip() or not self.policy_fingerprint.strip():
            raise ValueError("snapshot_id, instrument and policy_fingerprint are required")
        if self.signal_time.tzinfo is None:
            raise ValueError("signal_time must be timezone-aware")
        if len(self.payload_hash) != 64:
            raise ValueError("payload_hash must be a SHA-256 hex digest")
        try:
            int(self.payload_hash, 16)
        except ValueError as exc:
            raise ValueError("payload_hash must be a SHA-256 hex digest") from exc

    @classmethod
    def from_payload(
        cls,
        *,
        snapshot_id: str,
        instrument: str,
        signal_time: datetime,
        policy_fingerprint: str,
        payload: Mapping[str, object],
    ) -> FrozenAblationSnapshot:
        canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str).encode()
        return cls(
            snapshot_id=snapshot_id,
            instrument=instrument,
            signal_time=signal_time,
            policy_fingerprint=policy_fingerprint,
            payload_hash=hashlib.sha256(canonical).hexdigest(),
        )


@dataclass(frozen=True, slots=True)
class ProspectiveAblationDecision:
    snapshot_id: str
    snapshot_payload_hash: str
    policy_fingerprint: str
    instrument: str
    signal_time: datetime
    variant: AblationVariant
    tradeable: bool
    setup_family: str | None
    direction: str | None
    score: Decimal | None
    entry_price: Decimal | None
    stop_loss: Decimal | None
    take_profit: Decimal | None
    rejection_code: str | None
    error_type: str | None = None
    error_message: str | None = None

    def __post_init__(self) -> None:
        if not self.snapshot_id.strip() or not self.policy_fingerprint.strip() or not self.instrument.strip():
            raise ValueError("ablation decision identity is required")
        if self.signal_time.tzinfo is None:
            raise ValueError("signal_time must be timezone-aware")
        if len(self.snapshot_payload_hash) != 64:
            raise ValueError("snapshot_payload_hash must be a SHA-256 hex digest")
        if self.tradeable and self.error_type is not None:
            raise ValueError("errored ablation decisions cannot be tradeable")
        if self.tradeable and (self.entry_price is None or self.stop_loss is None or self.take_profit is None):
            raise ValueError("tradeable ablation decisions require entry/stop/target geometry")


AblationEvaluator = Callable[[FrozenAblationSnapshot, AblationVariant], ProspectiveAblationDecision]


class ProspectiveAblationCollector:
    """Run every declared ablation against one frozen point-in-time snapshot.

    The collector is intentionally evaluator-agnostic: production/research decision logic must
    be supplied by a caller. Its invariant is that all variants consume the same immutable
    snapshot identity before any outcome is known. An evaluator may abstain or fail, but the
    corresponding row remains in the paired denominator.
    """

    def __init__(
        self,
        evaluator: AblationEvaluator,
        *,
        variants: Iterable[AblationVariant] = REQUIRED_ABLATION_VARIANTS,
    ) -> None:
        self._evaluator = evaluator
        self._variants = tuple(variants)
        if not self._variants:
            raise ValueError("at least one ablation variant is required")
        if len(self._variants) != len(set(self._variants)):
            raise ValueError("ablation variants must be unique")
        if AblationVariant.FULL not in self._variants:
            raise ValueError("the full policy variant is required")

    @property
    def variants(self) -> tuple[AblationVariant, ...]:
        return self._variants

    def collect(self, snapshot: FrozenAblationSnapshot) -> tuple[ProspectiveAblationDecision, ...]:
        rows: list[ProspectiveAblationDecision] = []
        for variant in self._variants:
            try:
                row = self._evaluator(snapshot, variant)
            except Exception as exc:  # research evidence must retain evaluator failures
                row = ProspectiveAblationDecision(
                    snapshot_id=snapshot.snapshot_id,
                    snapshot_payload_hash=snapshot.payload_hash,
                    policy_fingerprint=snapshot.policy_fingerprint,
                    instrument=snapshot.instrument,
                    signal_time=snapshot.signal_time,
                    variant=variant,
                    tradeable=False,
                    setup_family=None,
                    direction=None,
                    score=None,
                    entry_price=None,
                    stop_loss=None,
                    take_profit=None,
                    rejection_code="evaluation_error",
                    error_type=type(exc).__name__,
                    error_message=str(exc)[:500],
                )
            self._validate_row(snapshot, variant, row)
            rows.append(row)
        return tuple(rows)

    @staticmethod
    def _validate_row(
        snapshot: FrozenAblationSnapshot,
        variant: AblationVariant,
        row: ProspectiveAblationDecision,
    ) -> None:
        if row.variant is not variant:
            raise ValueError(f"evaluator returned variant {row.variant}; expected {variant}")
        if row.snapshot_id != snapshot.snapshot_id:
            raise ValueError("ablation evaluator changed snapshot_id")
        if row.snapshot_payload_hash != snapshot.payload_hash:
            raise ValueError("ablation evaluator changed snapshot payload identity")
        if row.policy_fingerprint != snapshot.policy_fingerprint:
            raise ValueError("ablation evaluator changed policy_fingerprint")
        if row.instrument != snapshot.instrument or row.signal_time != snapshot.signal_time:
            raise ValueError("ablation evaluator changed point-in-time market identity")


@dataclass(frozen=True, slots=True)
class MaturedAblationOutcome:
    snapshot_id: str
    snapshot_payload_hash: str
    policy_fingerprint: str
    variant: AblationVariant
    realized_r: Decimal
    status: str

    def __post_init__(self) -> None:
        if not self.snapshot_id.strip() or not self.policy_fingerprint.strip():
            raise ValueError("matured ablation outcome identity is required")
        if len(self.snapshot_payload_hash) != 64:
            raise ValueError("snapshot_payload_hash must be a SHA-256 hex digest")
        if not self.status.strip():
            raise ValueError("matured ablation status is required")


@dataclass(frozen=True, slots=True)
class PairedAblationEvidence:
    name: str
    full_expectancy_r: Decimal
    ablated_expectancy_r: Decimal
    sample_size: int
    dataset_id: str

    def __post_init__(self) -> None:
        if not self.name.strip() or not self.dataset_id.strip():
            raise ValueError("paired ablation name and dataset_id are required")
        if self.sample_size < 1:
            raise ValueError("paired ablation sample_size must be positive")

    @property
    def component_increment_r(self) -> Decimal:
        return self.full_expectancy_r - self.ablated_expectancy_r


def paired_ablation_evidence(
    outcomes: Iterable[MaturedAblationOutcome],
    *,
    required_variants: Iterable[AblationVariant] = REQUIRED_ABLATION_VARIANTS,
) -> tuple[PairedAblationEvidence, ...]:
    variants = tuple(required_variants)
    if AblationVariant.FULL not in variants:
        raise ValueError("full variant is required")
    if len(variants) != len(set(variants)):
        raise ValueError("required variants must be unique")

    rows = tuple(outcomes)
    if not rows:
        raise ValueError("paired ablation evidence requires matured outcomes")
    grouped: dict[str, dict[AblationVariant, MaturedAblationOutcome]] = {}
    snapshot_identity: dict[str, tuple[str, str]] = {}
    for row in rows:
        if row.variant not in variants:
            continue
        current_identity = (row.snapshot_payload_hash, row.policy_fingerprint)
        prior_identity = snapshot_identity.setdefault(row.snapshot_id, current_identity)
        if prior_identity != current_identity:
            raise ValueError(f"snapshot {row.snapshot_id} has inconsistent payload/policy identity")
        bucket = grouped.setdefault(row.snapshot_id, {})
        if row.variant in bucket:
            raise ValueError(f"duplicate matured outcome for {row.snapshot_id}/{row.variant.value}")
        bucket[row.variant] = row

    expected = set(variants)
    for snapshot_id, bucket in grouped.items():
        missing = expected - set(bucket)
        if missing:
            names = ",".join(sorted(item.value for item in missing))
            raise ValueError(f"snapshot {snapshot_id} is missing paired variants: {names}")
    if not grouped:
        raise ValueError("no matured outcomes matched required variants")

    ordered_ids = tuple(sorted(grouped))
    full_values = tuple(grouped[snapshot_id][AblationVariant.FULL].realized_r for snapshot_id in ordered_ids)
    full_expectancy = sum(full_values, Decimal("0")) / Decimal(len(full_values))
    dataset_id = _paired_dataset_id(grouped, ordered_ids, variants)
    evidence: list[PairedAblationEvidence] = []
    for variant in variants:
        if variant is AblationVariant.FULL:
            continue
        values = tuple(grouped[snapshot_id][variant].realized_r for snapshot_id in ordered_ids)
        evidence.append(
            PairedAblationEvidence(
                name=variant.value,
                full_expectancy_r=full_expectancy,
                ablated_expectancy_r=sum(values, Decimal("0")) / Decimal(len(values)),
                sample_size=len(ordered_ids),
                dataset_id=dataset_id,
            )
        )
    return tuple(evidence)


def _paired_dataset_id(
    grouped: Mapping[str, Mapping[AblationVariant, MaturedAblationOutcome]],
    ordered_ids: tuple[str, ...],
    variants: tuple[AblationVariant, ...],
) -> str:
    payload = [
        {
            "snapshot_id": snapshot_id,
            "snapshot_payload_hash": grouped[snapshot_id][AblationVariant.FULL].snapshot_payload_hash,
            "policy_fingerprint": grouped[snapshot_id][AblationVariant.FULL].policy_fingerprint,
            "outcomes": {
                variant.value: {
                    "realized_r": str(grouped[snapshot_id][variant].realized_r),
                    "status": grouped[snapshot_id][variant].status,
                }
                for variant in variants
            },
        }
        for snapshot_id in ordered_ids
    ]
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(canonical).hexdigest()


def append_ablation_decisions(path: str | Path, rows: Iterable[ProspectiveAblationDecision]) -> int:
    file_path = Path(path)
    file_path.parent.mkdir(parents=True, exist_ok=True)
    count = 0
    with file_path.open("a", encoding="utf-8") as handle:
        for row in rows:
            payload = asdict(row)
            payload["signal_time"] = row.signal_time.isoformat()
            payload["variant"] = row.variant.value
            for field in ("score", "entry_price", "stop_loss", "take_profit"):
                value = payload[field]
                payload[field] = str(value) if value is not None else None
            handle.write(json.dumps(payload, sort_keys=True) + "\n")
            count += 1
    return count


def write_paired_ablation_evidence(path: str | Path, evidence: Iterable[PairedAblationEvidence]) -> None:
    values = tuple(evidence)
    if not values:
        raise ValueError("paired ablation evidence cannot be empty")
    dataset_ids = {item.dataset_id for item in values}
    sample_sizes = {item.sample_size for item in values}
    full_values = {item.full_expectancy_r for item in values}
    if len(dataset_ids) != 1 or len(sample_sizes) != 1 or len(full_values) != 1:
        raise ValueError("paired ablation evidence must share dataset, denominator and full baseline")
    payload = {
        "research_only": True,
        "execution_authority": False,
        "dataset_id": next(iter(dataset_ids)),
        "sample_size": next(iter(sample_sizes)),
        "ablations": [
            {
                "name": item.name,
                "full_expectancy_r": str(item.full_expectancy_r),
                "ablated_expectancy_r": str(item.ablated_expectancy_r),
                "sample_size": item.sample_size,
                "dataset_id": item.dataset_id,
            }
            for item in sorted(values, key=lambda item: item.name)
        ],
    }
    file_path = Path(path)
    file_path.parent.mkdir(parents=True, exist_ok=True)
    file_path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
