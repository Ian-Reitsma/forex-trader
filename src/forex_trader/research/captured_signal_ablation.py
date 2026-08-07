from __future__ import annotations

from dataclasses import replace

from forex_trader.application.signal_capture import SignalEvaluationInputs
from forex_trader.domain.enums import DecisionDisposition, OperatingMode
from forex_trader.domain.fusion import RegimeAwareSignalFusionPolicy
from forex_trader.domain.models import DecisionTrace
from forex_trader.research.ablation_runtime import ResearchAblationRequest
from forex_trader.research.ablations import FrozenAblationSnapshot, ProspectiveAblationDecision
from forex_trader.research.production_ablation import ProductionAblationAdapter, make_component_hooks
from forex_trader.research.production_signal_ablation import (
    ProductionSignalAblationEvaluator,
    freeze_production_signal_snapshot,
)


def freeze_captured_signal_snapshot(
    *,
    snapshot_id: str,
    policy_fingerprint: str,
    inputs: SignalEvaluationInputs,
) -> FrozenAblationSnapshot:
    """Freeze exact production signal inputs plus the actual context-hard-gate state."""
    base = freeze_production_signal_snapshot(
        snapshot_id=snapshot_id,
        policy_fingerprint=policy_fingerprint,
        instrument=inputs.instrument,
        lower_candles=inputs.lower_candles,
        higher_candles=inputs.higher_candles,
        quote=inputs.quote,
        fundamental=inputs.fundamental,
        maximum_spread_pips=inputs.maximum_spread_pips,
    )
    payload = base.require_payload()
    payload["event_blackout_reasons"] = list(inputs.event_blackout_reasons)
    payload["rollover_blackout"] = inputs.rollover_blackout
    return FrozenAblationSnapshot.from_payload(
        snapshot_id=base.snapshot_id,
        instrument=base.instrument,
        signal_time=base.signal_time,
        policy_fingerprint=base.policy_fingerprint,
        payload=payload,
    )


class CapturedProductionSignalAblationEvaluator:
    """Apply real production signal seams and frozen context gates to paired ablations."""

    def __init__(self, fusion_policy: RegimeAwareSignalFusionPolicy) -> None:
        self._base = ProductionSignalAblationEvaluator(fusion_policy)

    def evaluate_full(self, snapshot: FrozenAblationSnapshot) -> ProspectiveAblationDecision:
        return _apply_frozen_context_gates(
            self._base.evaluate_full(snapshot),
            snapshot,
            session_enabled=True,
        )

    def evaluate_masked(self, request: ResearchAblationRequest) -> ProspectiveAblationDecision:
        return _apply_frozen_context_gates(
            self._base.evaluate_masked(request),
            request.snapshot,
            session_enabled=request.mask.session,
        )

    def adapter(self) -> ProductionAblationAdapter:
        hooks = make_component_hooks(
            no_fundamentals=self.evaluate_masked,
            no_flow=self.evaluate_masked,
            no_session=self.evaluate_masked,
            no_zone_quality=self.evaluate_masked,
            no_retest=self.evaluate_masked,
        )
        return ProductionAblationAdapter(
            full_evaluator=self.evaluate_full,
            hooks=hooks,
            mode=OperatingMode.SHADOW,
            enable_paper_orders=False,
        )


def validate_full_against_trace(
    trace: DecisionTrace,
    row: ProspectiveAblationDecision,
) -> None:
    """Fail closed if the supposedly-full frozen replay differs from the actual decision."""
    candidate = trace.candidate
    expected_tradeable = candidate.disposition is DecisionDisposition.TRADE
    expected_setup = candidate.setup_family or None
    expected_direction = candidate.direction.value
    comparisons = (
        ("tradeable", row.tradeable, expected_tradeable),
        ("setup_family", row.setup_family, expected_setup),
        ("direction", row.direction, expected_direction),
        ("score", row.score, candidate.score),
        ("entry_price", row.entry_price, candidate.entry_price),
        ("stop_loss", row.stop_loss, candidate.stop_loss),
        ("take_profit", row.take_profit, candidate.take_profit),
        ("rejection_code", row.rejection_code, candidate.rejection_code),
    )
    mismatches = [name for name, actual, expected in comparisons if actual != expected]
    if mismatches:
        raise ValueError(
            "full frozen ablation replay diverged from actual production signal: "
            + ",".join(mismatches)
        )


def _apply_frozen_context_gates(
    row: ProspectiveAblationDecision,
    snapshot: FrozenAblationSnapshot,
    *,
    session_enabled: bool,
) -> ProspectiveAblationDecision:
    if not row.tradeable:
        return row
    payload = snapshot.require_payload()
    raw_reasons = payload.get("event_blackout_reasons", [])
    if not isinstance(raw_reasons, list):
        raise ValueError("frozen event_blackout_reasons must be an array")
    event_reasons = tuple(str(reason) for reason in raw_reasons if str(reason).strip())
    if event_reasons:
        return replace(
            row,
            tradeable=False,
            entry_price=None,
            stop_loss=None,
            take_profit=None,
            rejection_code="EVENT_BLACKOUT",
        )
    rollover = payload.get("rollover_blackout", False)
    if not isinstance(rollover, bool):
        raise ValueError("frozen rollover_blackout must be boolean")
    if session_enabled and rollover:
        return replace(
            row,
            tradeable=False,
            entry_price=None,
            stop_loss=None,
            take_profit=None,
            rejection_code="ROLLOVER_BLACKOUT",
        )
    return row
