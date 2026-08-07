from __future__ import annotations

from collections import defaultdict
from datetime import datetime
from decimal import Decimal
from typing import Iterable, Mapping, Sequence
from uuid import NAMESPACE_URL, uuid5

from forex_trader.domain.enums import DecisionDisposition, Direction
from forex_trader.domain.instruments import pip_size_for
from forex_trader.domain.models import Candle, TradeCandidate
from forex_trader.research.ablations import (
    REQUIRED_ABLATION_VARIANTS,
    AblationVariant,
    MaturedAblationOutcome,
    ProspectiveAblationDecision,
)
from forex_trader.research.backtest import OutcomeStatus, evaluate_candidate_outcome


def mature_ablation_outcomes(
    decisions: Iterable[ProspectiveAblationDecision],
    candles_by_instrument: Mapping[str, Sequence[Candle]],
    *,
    maximum_bars: int = 24,
    entry_slippage_pips: Decimal = Decimal("0"),
    exit_slippage_pips: Decimal = Decimal("0"),
    entry_delay_bars: int = 0,
    labeled_at: datetime,
    label_policy: str = "ohlc-conservative-ablation-v1",
) -> tuple[MaturedAblationOutcome, ...]:
    """Mature complete paired snapshots using the ordinary conservative outcome engine.

    The function is intentionally atomic by snapshot. Abstentions/evaluator failures count
    as 0R policy outcomes, but no rows for a snapshot are returned until every tradeable
    sibling is mature. A terminal stop/target may mature early; a timeout requires the full
    configured candle horizon. Tradeable rows require captured decision-time bid/ask so
    after-cost labeling cannot silently assume a zero spread.
    """
    if maximum_bars < 1:
        raise ValueError("maximum_bars must be positive")
    if entry_delay_bars < 0 or entry_delay_bars >= maximum_bars:
        raise ValueError("entry_delay_bars must be in [0, maximum_bars)")
    if entry_slippage_pips < 0 or exit_slippage_pips < 0:
        raise ValueError("slippage assumptions cannot be negative")
    if labeled_at.tzinfo is None:
        raise ValueError("labeled_at must be timezone-aware")
    if not label_policy.strip():
        raise ValueError("label_policy is required")

    groups = _group_complete_snapshots(tuple(decisions))
    matured: list[MaturedAblationOutcome] = []
    for snapshot_id in sorted(groups):
        bucket = groups[snapshot_id]
        first = bucket[AblationVariant.FULL]
        available = [
            candle
            for candle in candles_by_instrument.get(first.instrument, ())
            if candle.complete and first.signal_time <= candle.time <= labeled_at
        ]
        available.sort(key=lambda candle: candle.time)
        snapshot_rows: list[MaturedAblationOutcome] = []
        pending = False
        for variant in REQUIRED_ABLATION_VARIANTS:
            row = bucket[variant]
            if not row.tradeable:
                snapshot_rows.append(_zero_r_outcome(row, label_policy=label_policy))
                continue
            if not available or entry_delay_bars >= len(available):
                pending = True
                break
            trade = evaluate_candidate_outcome(
                _candidate_from_row(row),
                available,
                maximum_bars=maximum_bars,
                spread_pips=_spread_pips(row),
                entry_slippage_pips=entry_slippage_pips,
                exit_slippage_pips=exit_slippage_pips,
                entry_delay_bars=entry_delay_bars,
            )
            if trade.status is OutcomeStatus.TIMEOUT and len(available) < maximum_bars:
                pending = True
                break
            bar_index = min(max(1, trade.bars_held), len(available)) - 1
            snapshot_rows.append(
                MaturedAblationOutcome(
                    snapshot_id=row.snapshot_id,
                    snapshot_payload_hash=row.snapshot_payload_hash,
                    policy_fingerprint=row.policy_fingerprint,
                    variant=row.variant,
                    realized_r=trade.r_multiple,
                    status=trade.status.value,
                    labeled_at=available[bar_index].time,
                    label_policy=label_policy,
                    bars_held=trade.bars_held,
                    exit_reason=trade.exit_reason,
                    ambiguous_bar=trade.ambiguous_bar,
                    estimated_cost_r=trade.estimated_cost_r,
                )
            )
        if pending:
            continue
        if len(snapshot_rows) != len(REQUIRED_ABLATION_VARIANTS):
            raise RuntimeError(f"maturity lost paired rows for snapshot {snapshot_id}")
        matured.extend(snapshot_rows)
    return tuple(matured)


def validate_complete_matured_groups(outcomes: Iterable[MaturedAblationOutcome]) -> None:
    """Validate append-only maturity output before using it for resume or paired evidence."""
    grouped: dict[str, dict[AblationVariant, MaturedAblationOutcome]] = defaultdict(dict)
    identities: dict[str, tuple[str, str]] = {}
    for row in outcomes:
        identity = (row.snapshot_payload_hash, row.policy_fingerprint)
        prior = identities.setdefault(row.snapshot_id, identity)
        if prior != identity:
            raise ValueError(f"snapshot {row.snapshot_id} has inconsistent matured identity")
        bucket = grouped[row.snapshot_id]
        if row.variant in bucket:
            raise ValueError(f"duplicate matured outcome for {row.snapshot_id}/{row.variant.value}")
        bucket[row.variant] = row
    expected = set(REQUIRED_ABLATION_VARIANTS)
    for snapshot_id, bucket in grouped.items():
        missing = expected - set(bucket)
        if missing:
            names = ",".join(sorted(variant.value for variant in missing))
            raise ValueError(f"snapshot {snapshot_id} is missing matured variants: {names}")


def completed_snapshot_ids(outcomes: Iterable[MaturedAblationOutcome]) -> frozenset[str]:
    values = tuple(outcomes)
    validate_complete_matured_groups(values)
    return frozenset(row.snapshot_id for row in values)


def _group_complete_snapshots(
    rows: tuple[ProspectiveAblationDecision, ...],
) -> dict[str, dict[AblationVariant, ProspectiveAblationDecision]]:
    if not rows:
        raise ValueError("prospective ablation maturity requires decisions")
    grouped: dict[str, dict[AblationVariant, ProspectiveAblationDecision]] = defaultdict(dict)
    identities: dict[str, tuple[object, ...]] = {}
    for row in rows:
        identity = (
            row.snapshot_payload_hash,
            row.policy_fingerprint,
            row.instrument,
            row.signal_time,
            row.quote_bid,
            row.quote_ask,
        )
        prior = identities.setdefault(row.snapshot_id, identity)
        if prior != identity:
            raise ValueError(f"snapshot {row.snapshot_id} has inconsistent prospective identity")
        bucket = grouped[row.snapshot_id]
        if row.variant in bucket:
            raise ValueError(f"duplicate prospective decision for {row.snapshot_id}/{row.variant.value}")
        bucket[row.variant] = row
    expected = set(REQUIRED_ABLATION_VARIANTS)
    for snapshot_id, bucket in grouped.items():
        missing = expected - set(bucket)
        if missing:
            names = ",".join(sorted(variant.value for variant in missing))
            raise ValueError(f"snapshot {snapshot_id} is missing prospective variants: {names}")
    return dict(grouped)


def _zero_r_outcome(
    row: ProspectiveAblationDecision,
    *,
    label_policy: str,
) -> MaturedAblationOutcome:
    status = "evaluation_error" if row.error_type is not None else "abstain"
    reason = row.error_type or row.rejection_code or "no_trade"
    return MaturedAblationOutcome(
        snapshot_id=row.snapshot_id,
        snapshot_payload_hash=row.snapshot_payload_hash,
        policy_fingerprint=row.policy_fingerprint,
        variant=row.variant,
        realized_r=Decimal("0"),
        status=status,
        labeled_at=row.signal_time,
        label_policy=label_policy,
        bars_held=0,
        exit_reason=reason,
        ambiguous_bar=False,
        estimated_cost_r=Decimal("0"),
    )


def _candidate_from_row(row: ProspectiveAblationDecision) -> TradeCandidate:
    if not row.tradeable:
        raise ValueError("cannot build candidate from nontradeable ablation row")
    if row.direction is None or row.score is None:
        raise ValueError(f"tradeable ablation {row.snapshot_id}/{row.variant.value} lacks direction/score")
    if row.entry_price is None or row.stop_loss is None or row.take_profit is None:
        raise ValueError(f"tradeable ablation {row.snapshot_id}/{row.variant.value} lacks geometry")
    try:
        direction = Direction(row.direction)
    except ValueError as exc:
        raise ValueError(f"unsupported ablation direction: {row.direction}") from exc
    return TradeCandidate(
        candidate_id=uuid5(NAMESPACE_URL, f"{row.snapshot_id}:{row.variant.value}"),
        instrument=row.instrument,
        direction=direction,
        disposition=DecisionDisposition.TRADE,
        score=row.score,
        entry_price=row.entry_price,
        stop_loss=row.stop_loss,
        take_profit=row.take_profit,
        technical_score=row.score,
        fundamental_score=Decimal("0"),
        reasons=(),
        signal_time=row.signal_time,
        setup_family=row.setup_family or "",
        setup_state="",
        rejection_code=row.rejection_code,
        evidence={"ablation_variant": row.variant.value},
    )


def _spread_pips(row: ProspectiveAblationDecision) -> Decimal:
    if row.quote_bid is None or row.quote_ask is None:
        raise ValueError(
            f"tradeable ablation {row.snapshot_id}/{row.variant.value} lacks decision-time quote context"
        )
    pip = pip_size_for(row.instrument)
    if pip <= 0:
        raise ValueError("pip size must be positive")
    return max(Decimal("0"), row.quote_ask - row.quote_bid) / pip
