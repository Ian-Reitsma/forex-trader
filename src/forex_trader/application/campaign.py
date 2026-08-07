from __future__ import annotations

import hashlib
import json
import time
from collections import Counter
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Callable, Iterable, Mapping
from uuid import uuid4

from forex_trader.application.campaign_policy import campaign_policy_context, campaign_policy_fingerprint
from forex_trader.application.engine import TradingEngine
from forex_trader.application.signal_capture import SignalEvaluationInputs
from forex_trader.domain.enums import DecisionDisposition, OrderStatus, RiskDisposition
from forex_trader.domain.fusion import RegimeAwareSignalFusionPolicy
from forex_trader.domain.models import DecisionTrace
from forex_trader.research.ablations import ProspectiveAblationDecision, append_ablation_decisions
from forex_trader.research.captured_signal_ablation import (
    CapturedProductionSignalAblationEvaluator,
    freeze_captured_signal_snapshot,
    validate_full_against_trace,
)
from forex_trader.research.evidence import DecisionEvidence, append_decision_evidence
from forex_trader.research.production_ablation import ProductionAblationAdapter


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
    campaign_id: str
    policy_fingerprint: str
    policy_context: dict[str, object]
    campaign_metadata: dict[str, object]
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
    ablation_snapshots: int
    ablation_rows: int
    ablation_errors: int
    stopped_early: bool
    stop_reason: str | None
    rejection_codes: dict[str, int]
    risk_denial_reasons: dict[str, int]
    error_types: dict[str, int]
    ablation_error_types: dict[str, int]
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

    @property
    def ablation_snapshots(self) -> int:
        return sum(cycle.ablation_snapshots for cycle in self.cycles)

    @property
    def ablation_rows(self) -> int:
        return sum(cycle.ablation_rows for cycle in self.cycles)

    @property
    def ablation_errors(self) -> int:
        return sum(cycle.ablation_errors for cycle in self.cycles)


class PracticeCampaignRunner:
    """Run a conservative, evidence-first Practice campaign.

    Aggregate cycle evidence remains backward-compatible. An optional separate decision
    stream records every instrument evaluation with point-in-time strategy, regime,
    confirmation, risk and quote context. Shadow campaigns may additionally capture six
    paired production-signal ablations from the exact same frozen decision inputs. Paired
    capture is research-only and cannot coexist with campaign execution.
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
        decision_evidence_path: str | Path | None = None,
        ablation_evidence_path: str | Path | None = None,
        campaign_id: str | None = None,
        policy_context: Mapping[str, object] | None = None,
        campaign_metadata: Mapping[str, object] | None = None,
    ) -> None:
        normalized = tuple(dict.fromkeys(item.strip().upper() for item in instruments if item.strip()))
        if not normalized:
            raise ValueError("campaign requires at least one instrument")
        if max_new_orders_per_cycle < 0:
            raise ValueError("max_new_orders_per_cycle cannot be negative")
        resolved_campaign_id = (campaign_id or uuid4().hex).strip()
        if not resolved_campaign_id:
            raise ValueError("campaign_id cannot be empty")
        context = dict(policy_context) if policy_context is not None else _safe_policy_context(engine)
        self.engine = engine
        self.instruments = normalized
        self.execute = execute
        self.max_new_orders_per_cycle = max_new_orders_per_cycle
        self.stop_on_unresolved = stop_on_unresolved
        self.evidence_path = Path(evidence_path) if evidence_path is not None else None
        self.decision_evidence_path = Path(decision_evidence_path) if decision_evidence_path is not None else None
        self.ablation_evidence_path = Path(ablation_evidence_path) if ablation_evidence_path is not None else None
        self.campaign_id = resolved_campaign_id
        self.policy_context = context
        self.policy_fingerprint = campaign_policy_fingerprint(context)
        self.campaign_metadata = dict(campaign_metadata or {})
        self._signal_capture: Callable[..., tuple[DecisionTrace, SignalEvaluationInputs]] | None = None
        self._ablation_adapter: ProductionAblationAdapter | None = None
        if self.ablation_evidence_path is not None:
            if self.execute:
                raise ValueError("paired ablation capture is restricted to shadow campaigns")
            capture = getattr(engine, "evaluate_with_signal_inputs", None)
            if not callable(capture):
                raise ValueError("paired ablation capture requires an engine with signal-input capture")
            fusion_policy = getattr(engine, "fusion_policy", None)
            if not isinstance(fusion_policy, RegimeAwareSignalFusionPolicy):
                raise ValueError("paired ablation capture requires RegimeAwareSignalFusionPolicy")
            self._signal_capture = capture
            self._ablation_adapter = CapturedProductionSignalAblationEvaluator(fusion_policy).adapter()

    def run_cycle(self, cycle: int = 1) -> CampaignCycleReport:
        if cycle < 1:
            raise ValueError("cycle number must be positive")
        started = datetime.now(UTC)
        rejection_codes: Counter[str] = Counter()
        risk_denial_reasons: Counter[str] = Counter()
        error_types: Counter[str] = Counter()
        ablation_error_types: Counter[str] = Counter()
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
        ablation_snapshots = 0
        ablation_rows = 0
        ablation_errors = 0
        stopped_early = False
        stop_reason: str | None = None

        for instrument in self.instruments:
            may_submit = self.execute and submitted < self.max_new_orders_per_cycle
            captured_inputs: SignalEvaluationInputs | None = None
            try:
                if self._signal_capture is not None:
                    trace, captured_inputs = self._signal_capture(instrument, execute=False)
                else:
                    trace = self.engine.evaluate(instrument, execute=may_submit)
            except Exception as exc:
                errors += 1
                error_types[type(exc).__name__] += 1
                self._append_decision(
                    DecisionEvidence.from_error(
                        campaign_id=self.campaign_id,
                        policy_fingerprint=self.policy_fingerprint,
                        cycle=cycle,
                        instrument=instrument,
                        captured_at=datetime.now(UTC),
                        execution_enabled=may_submit,
                        error=exc,
                    )
                )
                continue

            self._append_decision(
                DecisionEvidence.from_trace(
                    trace,
                    campaign_id=self.campaign_id,
                    policy_fingerprint=self.policy_fingerprint,
                    cycle=cycle,
                    instrument=instrument,
                    captured_at=datetime.now(UTC),
                    execution_enabled=may_submit,
                )
            )
            evaluated += 1
            candidate = trace.candidate
            if candidate.disposition is DecisionDisposition.TRADE:
                trade_candidates += 1
            else:
                abstentions += 1
                rejection_codes[candidate.rejection_code or "UNSPECIFIED_ABSTENTION"] += 1

            if captured_inputs is not None:
                try:
                    rows = self._capture_ablations(
                        cycle=cycle,
                        instrument=instrument,
                        trace=trace,
                        inputs=captured_inputs,
                    )
                except Exception as exc:
                    ablation_errors += 1
                    ablation_error_types[type(exc).__name__] += 1
                else:
                    ablation_snapshots += 1
                    ablation_rows += len(rows)
                    for row in rows:
                        if row.error_type is not None:
                            ablation_errors += 1
                            ablation_error_types[row.error_type] += 1

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
            campaign_id=self.campaign_id,
            policy_fingerprint=self.policy_fingerprint,
            policy_context=dict(self.policy_context),
            campaign_metadata=dict(self.campaign_metadata),
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
            ablation_snapshots=ablation_snapshots,
            ablation_rows=ablation_rows,
            ablation_errors=ablation_errors,
            stopped_early=stopped_early,
            stop_reason=stop_reason,
            rejection_codes=dict(rejection_codes.most_common()),
            risk_denial_reasons=dict(risk_denial_reasons.most_common()),
            error_types=dict(error_types.most_common()),
            ablation_error_types=dict(ablation_error_types.most_common()),
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

    def _capture_ablations(
        self,
        *,
        cycle: int,
        instrument: str,
        trace: DecisionTrace,
        inputs: SignalEvaluationInputs,
    ) -> tuple[ProspectiveAblationDecision, ...]:
        if self._ablation_adapter is None or self.ablation_evidence_path is None:
            return ()
        snapshot = freeze_captured_signal_snapshot(
            snapshot_id=_ablation_snapshot_id(
                self.campaign_id,
                cycle,
                instrument,
                trace.candidate.signal_time,
            ),
            policy_fingerprint=self.policy_fingerprint,
            inputs=inputs,
        )
        rows = self._ablation_adapter.collect(snapshot)
        if not rows:
            raise ValueError("paired ablation adapter returned no rows")
        validate_full_against_trace(trace, rows[0])
        append_ablation_decisions(self.ablation_evidence_path, rows)
        return rows

    def _append_evidence(self, report: CampaignCycleReport) -> None:
        if self.evidence_path is None:
            return
        self.evidence_path.parent.mkdir(parents=True, exist_ok=True)
        with self.evidence_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(report.to_jsonable(), sort_keys=True))
            handle.write("\n")

    def _append_decision(self, record: DecisionEvidence) -> None:
        if self.decision_evidence_path is None:
            return
        append_decision_evidence(self.decision_evidence_path, record)


def _ablation_snapshot_id(
    campaign_id: str,
    cycle: int,
    instrument: str,
    signal_time: datetime,
) -> str:
    raw = f"{campaign_id}|{cycle}|{instrument.upper()}|{signal_time.isoformat()}".encode()
    return "ab-" + hashlib.sha256(raw).hexdigest()[:32]


def _safe_policy_context(engine: object) -> dict[str, object]:
    try:
        return campaign_policy_context(engine)  # type: ignore[arg-type]
    except (AttributeError, TypeError):
        return {
            "schema": "campaign-policy-v1",
            "engine_class": type(engine).__name__,
            "policy_introspection": "unavailable",
        }


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
