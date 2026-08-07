from __future__ import annotations

import json
import time
from collections import Counter
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Callable, Iterable

from forex_trader.application.engine import TradingEngine
from forex_trader.domain.enums import DecisionDisposition, OrderStatus, RiskDisposition


_UNRESOLVED_ORDER_STATUSES = {
    OrderStatus.CREATED,
    OrderStatus.ACKNOWLEDGED,
    OrderStatus.PARTIALLY_FILLED,
    OrderStatus.UNKNOWN,
    OrderStatus.RECONCILIATION_REQUIRED,
    OrderStatus.CLOSING,
    OrderStatus.EMERGENCY_CLOSE,
}


@dataclass(frozen=True, slots=True)
class CampaignCycleReport:
    cycle: int
    started_at: datetime
    finished_at: datetime
    instruments_requested: int
    instruments_evaluated: int
    trade_candidates: int
    abstentions: int
    risk_grants: int
    risk_denials: int
    orders_submitted: int
    orders_filled: int
    orders_protected: int
    orders_rejected: int
    orders_cancelled: int
    orders_unknown: int
    orders_reconciliation_required: int
    orders_emergency_close: int
    orders_unresolved: int
    errors: int
    stopped_early: bool
    stop_reason: str | None
    rejection_codes: dict[str, int]
    risk_denial_reasons: dict[str, int]
    error_types: dict[str, int]
    order_statuses: dict[str, int]
    promotion_ready: bool | None

    def to_jsonable(self) -> dict[str, object]:
        payload = asdict(self)
        payload["started_at"] = self.started_at.isoformat()
        payload["finished_at"] = self.finished_at.isoformat()
        return payload


@dataclass(frozen=True, slots=True)
class CampaignReport:
    cycles: tuple[CampaignCycleReport, ...]

    @property
    def evaluated(self) -> int:
        return sum(cycle.instruments_evaluated for cycle in self.cycles)

    @property
    def submitted(self) -> int:
        return sum(cycle.orders_submitted for cycle in self.cycles)

    @property
    def unknown(self) -> int:
        return sum(cycle.orders_unknown for cycle in self.cycles)

    @property
    def unresolved(self) -> int:
        return sum(cycle.orders_unresolved for cycle in self.cycles)


class PracticeCampaignRunner:
    """Run a conservative, evidence-first Practice campaign.

    The campaign never modifies strategy/risk thresholds. It caps new submissions per
    cycle, keeps evaluating the remaining universe in shadow after the submission budget
    is spent, records all broker order states, and stops immediately when a broker outcome
    is unresolved. TradingEngine remains the only component allowed to submit orders and
    retains execution locks, send-time revalidation, reconciliation and persistent halts.
    """

    def __init__(
        self,
        engine: TradingEngine,
        instruments: Iterable[str],
        *,
        execute: bool,
        max_new_orders_per_cycle: int = 1,
        stop_on_unresolved: bool = True,
        evidence_path: str | Path | None = None,
    ) -> None:
        normalized = tuple(dict.fromkeys(item.strip().upper() for item in instruments if item.strip()))
        if not normalized:
            raise ValueError("campaign requires at least one instrument")
        if max_new_orders_per_cycle < 0:
            raise ValueError("max_new_orders_per_cycle cannot be negative")
        self.engine = engine
        self.instruments = normalized
        self.execute = execute
        self.max_new_orders_per_cycle = max_new_orders_per_cycle
        self.stop_on_unresolved = stop_on_unresolved
        self.evidence_path = Path(evidence_path) if evidence_path is not None else None

    def run_cycle(self, cycle: int = 1) -> CampaignCycleReport:
        if cycle < 1:
            raise ValueError("cycle number must be positive")
        started = datetime.now(UTC)
        rejection_codes: Counter[str] = Counter()
        risk_denial_reasons: Counter[str] = Counter()
        error_types: Counter[str] = Counter()
        order_statuses: Counter[str] = Counter()
        evaluated = 0
        trade_candidates = 0
        abstentions = 0
        risk_grants = 0
        risk_denials = 0
        submitted = 0
        filled = 0
        protected = 0
        rejected = 0
        cancelled = 0
        unknown = 0
        reconciliation_required = 0
        emergency_close = 0
        unresolved = 0
        errors = 0
        stopped_early = False
        stop_reason: str | None = None

        for instrument in self.instruments:
            may_submit = self.execute and submitted < self.max_new_orders_per_cycle
            try:
                trace = self.engine.evaluate(instrument, execute=may_submit)
            except Exception as exc:
                errors += 1
                error_types[type(exc).__name__] += 1
                continue

            evaluated += 1
            candidate = trace.candidate
            if candidate.disposition is DecisionDisposition.TRADE:
                trade_candidates += 1
            else:
                abstentions += 1
                rejection_codes[candidate.rejection_code or "UNSPECIFIED_ABSTENTION"] += 1

            if trace.risk is not None:
                if trace.risk.disposition is RiskDisposition.GRANTED:
                    risk_grants += 1
                else:
                    risk_denials += 1
                    risk_denial_reasons[_primary_reason(trace.risk.reasons)] += 1

            if trace.order is None:
                continue
            submitted += 1
            status = trace.order.status
            order_statuses[status.value] += 1
            if status is OrderStatus.FILLED:
                filled += 1
            elif status is OrderStatus.PROTECTED:
                protected += 1
            elif status is OrderStatus.REJECTED:
                rejected += 1
            elif status is OrderStatus.CANCELLED:
                cancelled += 1
            elif status is OrderStatus.UNKNOWN:
                unknown += 1
            elif status is OrderStatus.RECONCILIATION_REQUIRED:
                reconciliation_required += 1
            elif status is OrderStatus.EMERGENCY_CLOSE:
                emergency_close += 1

            if status in _UNRESOLVED_ORDER_STATUSES:
                unresolved += 1
                if self.stop_on_unresolved:
                    stopped_early = True
                    stop_reason = (
                        f"broker order state {status.value} is unresolved; reconcile account "
                        "before evaluating/submitting remaining instruments"
                    )
                    break

        promotion_ready = _promotion_ready(self.engine)
        report = CampaignCycleReport(
            cycle=cycle,
            started_at=started,
            finished_at=datetime.now(UTC),
            instruments_requested=len(self.instruments),
            instruments_evaluated=evaluated,
            trade_candidates=trade_candidates,
            abstentions=abstentions,
            risk_grants=risk_grants,
            risk_denials=risk_denials,
            orders_submitted=submitted,
            orders_filled=filled,
            orders_protected=protected,
            orders_rejected=rejected,
            orders_cancelled=cancelled,
            orders_unknown=unknown,
            orders_reconciliation_required=reconciliation_required,
            orders_emergency_close=emergency_close,
            orders_unresolved=unresolved,
            errors=errors,
            stopped_early=stopped_early,
            stop_reason=stop_reason,
            rejection_codes=dict(rejection_codes.most_common()),
            risk_denial_reasons=dict(risk_denial_reasons.most_common()),
            error_types=dict(error_types.most_common()),
            order_statuses=dict(order_statuses.most_common()),
            promotion_ready=promotion_ready,
        )
        self._append_evidence(report)
        return report

    def run(
        self,
        *,
        max_cycles: int,
        interval_seconds: float,
        sleeper: Callable[[float], None] = time.sleep,
        on_cycle: Callable[[CampaignCycleReport], None] | None = None,
    ) -> CampaignReport:
        if max_cycles < 1:
            raise ValueError("max_cycles must be positive")
        if interval_seconds < 0:
            raise ValueError("interval_seconds cannot be negative")
        cycles: list[CampaignCycleReport] = []
        for cycle_number in range(1, max_cycles + 1):
            report = self.run_cycle(cycle_number)
            cycles.append(report)
            if on_cycle is not None:
                on_cycle(report)
            if report.orders_unresolved > 0 and self.stop_on_unresolved:
                break
            if cycle_number < max_cycles and interval_seconds:
                sleeper(interval_seconds)
        return CampaignReport(tuple(cycles))

    def _append_evidence(self, report: CampaignCycleReport) -> None:
        if self.evidence_path is None:
            return
        self.evidence_path.parent.mkdir(parents=True, exist_ok=True)
        with self.evidence_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(report.to_jsonable(), sort_keys=True))
            handle.write("\n")


def _primary_reason(reasons: tuple[str, ...]) -> str:
    if not reasons:
        return "UNSPECIFIED_RISK_DENIAL"
    reason = reasons[0].strip()
    return reason[:240] if reason else "UNSPECIFIED_RISK_DENIAL"


def _promotion_ready(engine: TradingEngine) -> bool | None:
    try:
        status = engine.promotion_status()
    except Exception:
        return None
    ready = status.get("ready") if isinstance(status, dict) else None
    return ready if isinstance(ready, bool) else None
