from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from typing import Iterable, Mapping

from forex_trader.domain.enums import Direction
from forex_trader.domain.models import Candle
from forex_trader.domain.technicals import pip_size
from forex_trader.research.backtest import BacktestTrade, OutcomeStatus
from forex_trader.research.cohorts import LabeledDecision
from forex_trader.research.evidence import DecisionEvidence, label_decision


@dataclass(frozen=True, slots=True)
class OutcomeEvidence:
    decision_key: str
    campaign_id: str
    policy_fingerprint: str
    instrument: str
    trace_id: str | None
    candidate_id: str | None
    signal_time: datetime
    labeled_at: datetime
    direction: str
    score: Decimal
    status: str
    r_multiple: Decimal
    bars_held: int
    exit_reason: str
    entry_fill: Decimal | None
    exit_fill: Decimal | None
    ambiguous_bar: bool
    maximum_favorable_r: Decimal
    maximum_adverse_r: Decimal
    estimated_cost_r: Decimal
    label_policy: str

    def to_jsonable(self) -> dict[str, object]:
        return {
            "decision_key": self.decision_key,
            "campaign_id": self.campaign_id,
            "policy_fingerprint": self.policy_fingerprint,
            "instrument": self.instrument,
            "trace_id": self.trace_id,
            "candidate_id": self.candidate_id,
            "signal_time": self.signal_time.isoformat(),
            "labeled_at": self.labeled_at.isoformat(),
            "direction": self.direction,
            "score": str(self.score),
            "status": self.status,
            "r_multiple": str(self.r_multiple),
            "bars_held": self.bars_held,
            "exit_reason": self.exit_reason,
            "entry_fill": str(self.entry_fill) if self.entry_fill is not None else None,
            "exit_fill": str(self.exit_fill) if self.exit_fill is not None else None,
            "ambiguous_bar": self.ambiguous_bar,
            "maximum_favorable_r": str(self.maximum_favorable_r),
            "maximum_adverse_r": str(self.maximum_adverse_r),
            "estimated_cost_r": str(self.estimated_cost_r),
            "label_policy": self.label_policy,
        }

    @classmethod
    def from_trade(
        cls,
        decision: DecisionEvidence,
        trade: BacktestTrade,
        *,
        labeled_at: datetime,
        label_policy: str,
    ) -> OutcomeEvidence:
        return cls(
            decision_key=decision_key(decision),
            campaign_id=decision.campaign_id,
            policy_fingerprint=decision.policy_fingerprint,
            instrument=trade.instrument,
            trace_id=decision.trace_id,
            candidate_id=decision.candidate_id,
            signal_time=trade.signal_time,
            labeled_at=labeled_at,
            direction=trade.direction.value,
            score=trade.score,
            status=trade.status.value,
            r_multiple=trade.r_multiple,
            bars_held=trade.bars_held,
            exit_reason=trade.exit_reason,
            entry_fill=trade.entry_fill,
            exit_fill=trade.exit_fill,
            ambiguous_bar=trade.ambiguous_bar,
            maximum_favorable_r=trade.maximum_favorable_r,
            maximum_adverse_r=trade.maximum_adverse_r,
            estimated_cost_r=trade.estimated_cost_r,
            label_policy=label_policy,
        )

    def to_trade(self) -> BacktestTrade:
        return BacktestTrade(
            instrument=self.instrument,
            direction=Direction(self.direction),
            signal_time=self.signal_time,
            score=self.score,
            status=OutcomeStatus(self.status),
            r_multiple=self.r_multiple,
            bars_held=self.bars_held,
            exit_reason=self.exit_reason,
            entry_fill=self.entry_fill,
            exit_fill=self.exit_fill,
            ambiguous_bar=self.ambiguous_bar,
            maximum_favorable_r=self.maximum_favorable_r,
            maximum_adverse_r=self.maximum_adverse_r,
            estimated_cost_r=self.estimated_cost_r,
        )


def decision_key(decision: DecisionEvidence) -> str:
    if decision.candidate_id:
        return f"candidate:{decision.candidate_id}"
    if decision.trace_id:
        return f"trace:{decision.trace_id}"
    return f"attempt:{decision.campaign_id}:{decision.cycle}:{decision.instrument}"


def append_outcome_evidence(path: str | Path, outcome: OutcomeEvidence) -> None:
    file_path = Path(path)
    file_path.parent.mkdir(parents=True, exist_ok=True)
    with file_path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(outcome.to_jsonable(), sort_keys=True, separators=(",", ":")))
        handle.write("\n")


def load_outcome_evidence(path: str | Path) -> tuple[OutcomeEvidence, ...]:
    file_path = Path(path)
    if not file_path.is_file():
        raise FileNotFoundError(file_path)
    rows: list[OutcomeEvidence] = []
    seen: set[str] = set()
    for line_number, raw in enumerate(file_path.read_text(encoding="utf-8").splitlines(), start=1):
        if not raw.strip():
            continue
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise ValueError(f"invalid outcome evidence JSONL line {line_number}: {exc.msg}") from exc
        if not isinstance(payload, dict):
            raise ValueError(f"invalid outcome evidence JSONL line {line_number}: expected object")
        row = _outcome_from_payload(payload, line_number=line_number)
        if row.decision_key in seen:
            raise ValueError(f"duplicate outcome decision_key at line {line_number}: {row.decision_key}")
        seen.add(row.decision_key)
        rows.append(row)
    if not rows:
        raise ValueError("outcome evidence file contains no records")
    return tuple(rows)


def label_mature_decisions(
    decisions: Iterable[DecisionEvidence],
    candles_by_instrument: Mapping[str, list[Candle]],
    *,
    maximum_bars: int = 24,
    spread_from_decision_quote: bool = True,
    entry_slippage_pips: Decimal = Decimal("0"),
    exit_slippage_pips: Decimal = Decimal("0"),
    entry_delay_bars: int = 0,
    labeled_at: datetime,
    label_policy: str = "ohlc-conservative-v1",
) -> tuple[OutcomeEvidence, ...]:
    if maximum_bars < 1:
        raise ValueError("maximum_bars must be positive")
    if labeled_at.tzinfo is None:
        raise ValueError("labeled_at must be timezone-aware")
    outcomes: list[OutcomeEvidence] = []
    for decision in decisions:
        if not decision.is_trade_candidate or decision.signal_time is None:
            continue
        available = [
            candle
            for candle in candles_by_instrument.get(decision.instrument, [])
            if candle.complete and candle.time >= decision.signal_time and candle.time <= labeled_at
        ]
        if not available:
            continue
        spread_pips = _decision_spread_pips(decision) if spread_from_decision_quote else Decimal("0")
        trade = label_decision(
            decision,
            available,
            maximum_bars=maximum_bars,
            spread_pips=spread_pips,
            entry_slippage_pips=entry_slippage_pips,
            exit_slippage_pips=exit_slippage_pips,
            entry_delay_bars=entry_delay_bars,
        )
        # A target/stop is terminal as soon as observed. A timeout label is valid only
        # after the full observation horizon exists; otherwise it would leak a partial
        # live path into the historical training set as a false timeout.
        if trade.status is OutcomeStatus.TIMEOUT and len(available) < maximum_bars:
            continue
        bar_index = min(max(1, trade.bars_held), len(available)) - 1
        outcomes.append(
            OutcomeEvidence.from_trade(
                decision,
                trade,
                labeled_at=available[bar_index].time,
                label_policy=label_policy,
            )
        )
    return tuple(outcomes)


def join_labeled_decisions(
    decisions: Iterable[DecisionEvidence],
    outcomes: Iterable[OutcomeEvidence],
) -> tuple[LabeledDecision, ...]:
    outcome_map = {row.decision_key: row for row in outcomes}
    joined: list[LabeledDecision] = []
    for decision in decisions:
        row = outcome_map.get(decision_key(decision))
        if row is None:
            continue
        if row.campaign_id != decision.campaign_id:
            raise ValueError(f"campaign mismatch for {row.decision_key}")
        if row.policy_fingerprint != decision.policy_fingerprint:
            raise ValueError(f"policy fingerprint mismatch for {row.decision_key}")
        if row.instrument != decision.instrument:
            raise ValueError(f"instrument mismatch for {row.decision_key}")
        if decision.signal_time is None or row.signal_time != decision.signal_time:
            raise ValueError(f"signal time mismatch for {row.decision_key}")
        joined.append(LabeledDecision(decision=decision, outcome=row.to_trade()))
    return tuple(joined)


def reward_r_from_geometry(decision: DecisionEvidence) -> Decimal:
    if decision.entry_price is None or decision.stop_loss is None or decision.take_profit is None:
        raise ValueError("decision is missing executable geometry")
    risk = abs(decision.entry_price - decision.stop_loss)
    if risk <= 0:
        raise ValueError("decision stop distance must be positive")
    return abs(decision.take_profit - decision.entry_price) / risk


def spread_cost_r_from_quote(decision: DecisionEvidence) -> Decimal:
    if decision.entry_price is None or decision.stop_loss is None:
        raise ValueError("decision is missing entry/stop geometry")
    if decision.quote_bid is None or decision.quote_ask is None:
        return Decimal("0")
    risk = abs(decision.entry_price - decision.stop_loss)
    if risk <= 0:
        raise ValueError("decision stop distance must be positive")
    return max(Decimal("0"), decision.quote_ask - decision.quote_bid) / risk


def _decision_spread_pips(decision: DecisionEvidence) -> Decimal:
    if decision.quote_bid is None or decision.quote_ask is None:
        return Decimal("0")
    pip = pip_size(decision.instrument)
    if pip <= 0:
        raise ValueError("pip size must be positive")
    return max(Decimal("0"), decision.quote_ask - decision.quote_bid) / pip


def _outcome_from_payload(payload: Mapping[str, object], *, line_number: int) -> OutcomeEvidence:
    try:
        return OutcomeEvidence(
            decision_key=_required_text(payload.get("decision_key"), "decision_key"),
            campaign_id=_required_text(payload.get("campaign_id"), "campaign_id"),
            policy_fingerprint=_required_text(payload.get("policy_fingerprint"), "policy_fingerprint"),
            instrument=_required_text(payload.get("instrument"), "instrument"),
            trace_id=_optional_text(payload.get("trace_id")),
            candidate_id=_optional_text(payload.get("candidate_id")),
            signal_time=_required_datetime(payload.get("signal_time"), "signal_time"),
            labeled_at=_required_datetime(payload.get("labeled_at"), "labeled_at"),
            direction=_required_text(payload.get("direction"), "direction"),
            score=_required_decimal(payload.get("score"), "score"),
            status=_required_text(payload.get("status"), "status"),
            r_multiple=_required_decimal(payload.get("r_multiple"), "r_multiple"),
            bars_held=_required_integer(payload.get("bars_held"), "bars_held"),
            exit_reason=_optional_text(payload.get("exit_reason")) or "",
            entry_fill=_optional_decimal(payload.get("entry_fill")),
            exit_fill=_optional_decimal(payload.get("exit_fill")),
            ambiguous_bar=_required_bool(payload.get("ambiguous_bar"), "ambiguous_bar"),
            maximum_favorable_r=_required_decimal(payload.get("maximum_favorable_r"), "maximum_favorable_r"),
            maximum_adverse_r=_required_decimal(payload.get("maximum_adverse_r"), "maximum_adverse_r"),
            estimated_cost_r=_required_decimal(payload.get("estimated_cost_r"), "estimated_cost_r"),
            label_policy=_required_text(payload.get("label_policy"), "label_policy"),
        )
    except (TypeError, ValueError) as exc:
        raise ValueError(f"invalid outcome evidence JSONL line {line_number}: {exc}") from exc


def _optional_text(value: object) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _required_text(value: object, name: str) -> str:
    text = _optional_text(value)
    if text is None:
        raise ValueError(f"{name} is required")
    return text


def _optional_decimal(value: object) -> Decimal | None:
    if value is None or value == "":
        return None
    return Decimal(str(value))


def _required_decimal(value: object, name: str) -> Decimal:
    parsed = _optional_decimal(value)
    if parsed is None:
        raise ValueError(f"{name} is required")
    return parsed


def _required_integer(value: object, name: str) -> int:
    if value is None or value == "":
        raise ValueError(f"{name} is required")
    return int(str(value))


def _required_datetime(value: object, name: str) -> datetime:
    if value is None or value == "":
        raise ValueError(f"{name} is required")
    parsed = value if isinstance(value, datetime) else datetime.fromisoformat(str(value))
    if parsed.tzinfo is None:
        raise ValueError(f"{name} must be timezone-aware")
    return parsed


def _required_bool(value: object, name: str) -> bool:
    if isinstance(value, bool):
        return value
    raise ValueError(f"{name} must be a boolean")
