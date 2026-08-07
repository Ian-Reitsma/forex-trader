from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from typing import Mapping
from uuid import NAMESPACE_URL, UUID, uuid5

from forex_trader.domain.enums import DecisionDisposition, Direction
from forex_trader.domain.models import Candle, TradeCandidate
from forex_trader.research.backtest import BacktestTrade, evaluate_candidate_outcome


@dataclass(frozen=True, slots=True)
class DecisionEvidence:
    campaign_id: str
    policy_fingerprint: str
    cycle: int
    instrument: str
    trace_id: str | None
    candidate_id: str | None
    captured_at: datetime
    signal_time: datetime | None
    direction: str | None
    disposition: str | None
    setup_family: str
    setup_state: str
    rejection_code: str | None
    score: Decimal | None
    technical_score: Decimal | None
    fundamental_score: Decimal | None
    fundamental_confidence: Decimal | None
    entry_price: Decimal | None
    stop_loss: Decimal | None
    take_profit: Decimal | None
    quote_bid: Decimal | None
    quote_ask: Decimal | None
    quote_time: datetime | None
    regime: str
    session_phase: str
    selected_policy: str
    policy_authority: str
    confirmation_categories: tuple[str, ...]
    confirmation_source_ids: tuple[str, ...]
    risk_disposition: str | None
    risk_units: int | None
    risk_amount: Decimal | None
    order_status: str | None
    execution_enabled: bool
    candidate_evidence: Mapping[str, object]
    error_type: str | None = None
    error_message: str | None = None

    @property
    def is_trade_candidate(self) -> bool:
        return self.disposition == DecisionDisposition.TRADE.value

    @property
    def cohort_key(self) -> str:
        return cohort_key(self)

    def to_jsonable(self) -> dict[str, object]:
        safe = _json_safe(
            {
                "campaign_id": self.campaign_id,
                "policy_fingerprint": self.policy_fingerprint,
                "cycle": self.cycle,
                "instrument": self.instrument,
                "trace_id": self.trace_id,
                "candidate_id": self.candidate_id,
                "captured_at": self.captured_at,
                "signal_time": self.signal_time,
                "direction": self.direction,
                "disposition": self.disposition,
                "setup_family": self.setup_family,
                "setup_state": self.setup_state,
                "rejection_code": self.rejection_code,
                "score": self.score,
                "technical_score": self.technical_score,
                "fundamental_score": self.fundamental_score,
                "fundamental_confidence": self.fundamental_confidence,
                "entry_price": self.entry_price,
                "stop_loss": self.stop_loss,
                "take_profit": self.take_profit,
                "quote_bid": self.quote_bid,
                "quote_ask": self.quote_ask,
                "quote_time": self.quote_time,
                "regime": self.regime,
                "session_phase": self.session_phase,
                "selected_policy": self.selected_policy,
                "policy_authority": self.policy_authority,
                "confirmation_categories": self.confirmation_categories,
                "confirmation_source_ids": self.confirmation_source_ids,
                "risk_disposition": self.risk_disposition,
                "risk_units": self.risk_units,
                "risk_amount": self.risk_amount,
                "order_status": self.order_status,
                "execution_enabled": self.execution_enabled,
                "candidate_evidence": self.candidate_evidence,
                "error_type": self.error_type,
                "error_message": self.error_message,
            }
        )
        if not isinstance(safe, dict):
            raise TypeError("decision evidence serialization must produce an object")
        return {str(key): value for key, value in safe.items()}

    @classmethod
    def from_trace(
        cls,
        trace: object,
        *,
        campaign_id: str,
        policy_fingerprint: str,
        cycle: int,
        instrument: str,
        captured_at: datetime,
        execution_enabled: bool,
    ) -> DecisionEvidence:
        candidate = getattr(trace, "candidate", None)
        risk = getattr(trace, "risk", None)
        order = getattr(trace, "order", None)
        quote = getattr(trace, "quote", None)
        metadata = _mapping(getattr(trace, "metadata", None))
        evidence = _mapping(getattr(candidate, "evidence", None))
        return cls(
            campaign_id=campaign_id,
            policy_fingerprint=policy_fingerprint,
            cycle=cycle,
            instrument=instrument,
            trace_id=_text(getattr(trace, "trace_id", None)),
            candidate_id=_text(getattr(candidate, "candidate_id", None)),
            captured_at=captured_at,
            signal_time=_datetime(getattr(candidate, "signal_time", None)),
            direction=_enum_text(getattr(candidate, "direction", None)),
            disposition=_enum_text(getattr(candidate, "disposition", None)),
            setup_family=_text(getattr(candidate, "setup_family", None)) or "",
            setup_state=_text(getattr(candidate, "setup_state", None)) or "",
            rejection_code=_text(getattr(candidate, "rejection_code", None)),
            score=_decimal(getattr(candidate, "score", None)),
            technical_score=_decimal(getattr(candidate, "technical_score", None)),
            fundamental_score=_decimal(getattr(candidate, "fundamental_score", None)),
            fundamental_confidence=_decimal(getattr(candidate, "fundamental_confidence", None)),
            entry_price=_decimal(getattr(candidate, "entry_price", None)),
            stop_loss=_decimal(getattr(candidate, "stop_loss", None)),
            take_profit=_decimal(getattr(candidate, "take_profit", None)),
            quote_bid=_decimal(getattr(quote, "bid", None)),
            quote_ask=_decimal(getattr(quote, "ask", None)),
            quote_time=_datetime(getattr(quote, "time", None)),
            regime=_text(evidence.get("regime")) or _text(metadata.get("regime")) or "unknown",
            session_phase=_text(metadata.get("session_phase")) or "unknown",
            selected_policy=_text(evidence.get("selected_policy")) or _text(metadata.get("strategy_policy")) or "unknown",
            policy_authority=_text(evidence.get("policy_authority")) or "unknown",
            confirmation_categories=_string_tuple(evidence.get("confirmation_categories")),
            confirmation_source_ids=_string_tuple(evidence.get("confirmation_source_ids")),
            risk_disposition=_enum_text(getattr(risk, "disposition", None)),
            risk_units=_integer(getattr(risk, "units", None)),
            risk_amount=_decimal(getattr(risk, "risk_amount", None)),
            order_status=_enum_text(getattr(order, "status", None)),
            execution_enabled=execution_enabled,
            candidate_evidence=evidence,
        )

    @classmethod
    def from_error(
        cls,
        *,
        campaign_id: str,
        policy_fingerprint: str,
        cycle: int,
        instrument: str,
        captured_at: datetime,
        execution_enabled: bool,
        error: Exception,
    ) -> DecisionEvidence:
        return cls(
            campaign_id=campaign_id,
            policy_fingerprint=policy_fingerprint,
            cycle=cycle,
            instrument=instrument,
            trace_id=None,
            candidate_id=None,
            captured_at=captured_at,
            signal_time=None,
            direction=None,
            disposition=None,
            setup_family="",
            setup_state="",
            rejection_code=None,
            score=None,
            technical_score=None,
            fundamental_score=None,
            fundamental_confidence=None,
            entry_price=None,
            stop_loss=None,
            take_profit=None,
            quote_bid=None,
            quote_ask=None,
            quote_time=None,
            regime="unknown",
            session_phase="unknown",
            selected_policy="unknown",
            policy_authority="unknown",
            confirmation_categories=(),
            confirmation_source_ids=(),
            risk_disposition=None,
            risk_units=None,
            risk_amount=None,
            order_status=None,
            execution_enabled=execution_enabled,
            candidate_evidence={},
            error_type=type(error).__name__,
            error_message=str(error)[:500],
        )


def append_decision_evidence(path: str | Path, record: DecisionEvidence) -> None:
    file_path = Path(path)
    file_path.parent.mkdir(parents=True, exist_ok=True)
    with file_path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(record.to_jsonable(), sort_keys=True, separators=(",", ":")))
        handle.write("\n")


def load_decision_evidence(path: str | Path) -> tuple[DecisionEvidence, ...]:
    file_path = Path(path)
    if not file_path.is_file():
        raise FileNotFoundError(file_path)
    records: list[DecisionEvidence] = []
    for line_number, raw in enumerate(file_path.read_text(encoding="utf-8").splitlines(), start=1):
        if not raw.strip():
            continue
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise ValueError(f"invalid decision evidence JSONL line {line_number}: {exc.msg}") from exc
        if not isinstance(payload, dict):
            raise ValueError(f"invalid decision evidence JSONL line {line_number}: expected object")
        records.append(_from_payload(payload, line_number=line_number))
    if not records:
        raise ValueError("decision evidence file contains no records")
    return tuple(records)


def cohort_key(record: DecisionEvidence, *, include_instrument: bool = False) -> str:
    parts = [
        record.setup_family or "unknown_setup",
        record.regime or "unknown_regime",
        record.session_phase or "unknown_session",
    ]
    if include_instrument:
        parts.append(record.instrument)
    return "|".join(parts)


def candidate_from_evidence(record: DecisionEvidence) -> TradeCandidate:
    if not record.is_trade_candidate:
        raise ValueError("decision evidence is not a trade candidate")
    if record.signal_time is None or record.direction is None:
        raise ValueError("trade decision evidence is missing signal time or direction")
    if record.score is None or record.entry_price is None or record.stop_loss is None or record.take_profit is None:
        raise ValueError("trade decision evidence is missing executable geometry")
    try:
        direction = Direction(record.direction)
    except ValueError as exc:
        raise ValueError(f"unsupported decision direction: {record.direction}") from exc
    return TradeCandidate(
        candidate_id=_uuid_for_evidence(record),
        instrument=record.instrument,
        direction=direction,
        disposition=DecisionDisposition.TRADE,
        score=record.score,
        entry_price=record.entry_price,
        stop_loss=record.stop_loss,
        take_profit=record.take_profit,
        technical_score=record.technical_score or Decimal("0"),
        fundamental_score=record.fundamental_score or Decimal("0"),
        reasons=(),
        signal_time=record.signal_time,
        setup_family=record.setup_family,
        setup_state=record.setup_state,
        rejection_code=record.rejection_code,
        fundamental_confidence=record.fundamental_confidence or Decimal("0"),
        evidence=dict(record.candidate_evidence),
    )


def label_decision(
    record: DecisionEvidence,
    future_candles: list[Candle],
    *,
    maximum_bars: int = 24,
    spread_pips: Decimal = Decimal("0"),
    entry_slippage_pips: Decimal = Decimal("0"),
    exit_slippage_pips: Decimal = Decimal("0"),
    entry_delay_bars: int = 0,
) -> BacktestTrade:
    return evaluate_candidate_outcome(
        candidate_from_evidence(record),
        future_candles,
        maximum_bars=maximum_bars,
        spread_pips=spread_pips,
        entry_slippage_pips=entry_slippage_pips,
        exit_slippage_pips=exit_slippage_pips,
        entry_delay_bars=entry_delay_bars,
    )


def _from_payload(payload: Mapping[str, object], *, line_number: int) -> DecisionEvidence:
    try:
        captured_at = _required_datetime(payload.get("captured_at"), "captured_at")
        return DecisionEvidence(
            campaign_id=str(payload["campaign_id"]),
            policy_fingerprint=str(payload["policy_fingerprint"]),
            cycle=_required_integer(payload.get("cycle"), "cycle"),
            instrument=str(payload["instrument"]),
            trace_id=_text(payload.get("trace_id")),
            candidate_id=_text(payload.get("candidate_id")),
            captured_at=captured_at,
            signal_time=_optional_datetime(payload.get("signal_time"), "signal_time"),
            direction=_text(payload.get("direction")),
            disposition=_text(payload.get("disposition")),
            setup_family=_text(payload.get("setup_family")) or "",
            setup_state=_text(payload.get("setup_state")) or "",
            rejection_code=_text(payload.get("rejection_code")),
            score=_decimal(payload.get("score")),
            technical_score=_decimal(payload.get("technical_score")),
            fundamental_score=_decimal(payload.get("fundamental_score")),
            fundamental_confidence=_decimal(payload.get("fundamental_confidence")),
            entry_price=_decimal(payload.get("entry_price")),
            stop_loss=_decimal(payload.get("stop_loss")),
            take_profit=_decimal(payload.get("take_profit")),
            quote_bid=_decimal(payload.get("quote_bid")),
            quote_ask=_decimal(payload.get("quote_ask")),
            quote_time=_optional_datetime(payload.get("quote_time"), "quote_time"),
            regime=_text(payload.get("regime")) or "unknown",
            session_phase=_text(payload.get("session_phase")) or "unknown",
            selected_policy=_text(payload.get("selected_policy")) or "unknown",
            policy_authority=_text(payload.get("policy_authority")) or "unknown",
            confirmation_categories=_string_tuple(payload.get("confirmation_categories")),
            confirmation_source_ids=_string_tuple(payload.get("confirmation_source_ids")),
            risk_disposition=_text(payload.get("risk_disposition")),
            risk_units=_integer(payload.get("risk_units")),
            risk_amount=_decimal(payload.get("risk_amount")),
            order_status=_text(payload.get("order_status")),
            execution_enabled=bool(payload.get("execution_enabled", False)),
            candidate_evidence=_mapping(payload.get("candidate_evidence")),
            error_type=_text(payload.get("error_type")),
            error_message=_text(payload.get("error_message")),
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError(f"invalid decision evidence JSONL line {line_number}: {exc}") from exc


def _uuid_for_evidence(record: DecisionEvidence) -> UUID:
    if record.candidate_id:
        try:
            return UUID(record.candidate_id)
        except ValueError:
            pass
    return uuid5(NAMESPACE_URL, f"{record.campaign_id}:{record.cycle}:{record.instrument}:{record.trace_id or ''}")


def _mapping(value: object) -> dict[str, object]:
    if not isinstance(value, Mapping):
        return {}
    return {str(key): item for key, item in value.items()}


def _enum_text(value: object) -> str | None:
    raw = getattr(value, "value", value)
    return _text(raw)


def _text(value: object) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _decimal(value: object) -> Decimal | None:
    if value is None or value == "":
        return None
    if isinstance(value, Decimal):
        return value
    return Decimal(str(value))


def _integer(value: object) -> int | None:
    if value is None or value == "":
        return None
    return int(str(value))


def _required_integer(value: object, name: str) -> int:
    parsed = _integer(value)
    if parsed is None:
        raise ValueError(f"{name} is required")
    return parsed


def _datetime(value: object) -> datetime | None:
    return value if isinstance(value, datetime) else None


def _required_datetime(value: object, name: str) -> datetime:
    parsed = _optional_datetime(value, name)
    if parsed is None:
        raise ValueError(f"{name} is required")
    return parsed


def _optional_datetime(value: object, name: str) -> datetime | None:
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        parsed = value
    else:
        parsed = datetime.fromisoformat(str(value))
    if parsed.tzinfo is None:
        raise ValueError(f"{name} must be timezone-aware")
    return parsed


def _string_tuple(value: object) -> tuple[str, ...]:
    if isinstance(value, (list, tuple)):
        return tuple(str(item) for item in value if str(item))
    return ()


def _json_safe(value: object) -> object:
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, Mapping):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        return [_json_safe(item) for item in value]
    if hasattr(value, "value"):
        return _json_safe(getattr(value, "value"))
    return value
