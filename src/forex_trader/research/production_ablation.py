from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Mapping

from forex_trader.domain.enums import OperatingMode
from forex_trader.research.ablation_runtime import FEATURE_MASKS, ResearchAblationRequest, ShadowAblationRuntime
from forex_trader.research.ablations import AblationVariant, FrozenAblationSnapshot, ProspectiveAblationDecision


ProductionShadowEvaluator = Callable[[FrozenAblationSnapshot], ProspectiveAblationDecision]
MaskedProductionEvaluator = Callable[[ResearchAblationRequest], ProspectiveAblationDecision]


@dataclass(frozen=True, slots=True)
class ComponentAblationHook:
    """One explicit production-pipeline component hook.

    The hook is intentionally declarative. The adapter refuses a hook whose declared
    component does not match the variant's single disabled feature, preventing a research
    evaluator from silently changing multiple components under one ablation name.
    """

    variant: AblationVariant
    component: str
    evaluator: MaskedProductionEvaluator

    def __post_init__(self) -> None:
        if self.variant is AblationVariant.FULL:
            raise ValueError("full production evaluation is supplied separately, not as an ablation hook")
        disabled = FEATURE_MASKS[self.variant].disabled_components
        if disabled != (self.component,):
            raise ValueError(
                f"hook component {self.component!r} does not match variant {self.variant.value}: {disabled}"
            )


class ProductionAblationAdapter:
    """Bridge the real shadow decision path into prospective paired ablations.

    `full_evaluator` must be the normal shadow decision path operating only on the frozen
    snapshot payload. Each masked variant requires an explicit production-pipeline hook.
    Missing hooks fail at construction. This module contains no broker and cannot enable
    execution; `ShadowAblationRuntime` provides the hard authority boundary.
    """

    def __init__(
        self,
        *,
        full_evaluator: ProductionShadowEvaluator,
        hooks: Mapping[AblationVariant, ComponentAblationHook],
        mode: OperatingMode,
        enable_paper_orders: bool,
    ) -> None:
        if mode is not OperatingMode.SHADOW:
            raise ValueError("production ablation adapter is restricted to shadow mode")
        if enable_paper_orders:
            raise ValueError("production ablation adapter cannot enable paper broker writes")
        self._full_evaluator = full_evaluator
        self._hooks = dict(hooks)
        expected = set(AblationVariant) - {AblationVariant.FULL}
        actual = set(self._hooks)
        missing = expected - actual
        extra = actual - expected
        if missing or extra:
            missing_text = ",".join(sorted(item.value for item in missing)) or "none"
            extra_text = ",".join(sorted(item.value for item in extra)) or "none"
            raise ValueError(f"production ablation hooks incomplete: missing={missing_text}; extra={extra_text}")
        for variant, hook in self._hooks.items():
            if hook.variant is not variant:
                raise ValueError(
                    f"production ablation hook key {variant.value} does not match hook variant {hook.variant.value}"
                )
        self._runtime = ShadowAblationRuntime(
            self._evaluate_request,
            mode=mode,
            enable_paper_orders=enable_paper_orders,
        )

    def collect(self, snapshot: FrozenAblationSnapshot) -> tuple[ProspectiveAblationDecision, ...]:
        return self._runtime.collect(snapshot)

    def evaluate_full(self, snapshot: FrozenAblationSnapshot) -> ProspectiveAblationDecision:
        row = self._full_evaluator(snapshot)
        self._validate_full(snapshot, row)
        return row

    def _evaluate_request(self, request: ResearchAblationRequest) -> ProspectiveAblationDecision:
        if request.variant is AblationVariant.FULL:
            return self.evaluate_full(request.snapshot)
        hook = self._hooks[request.variant]
        row = hook.evaluator(request)
        self._validate_masked(request, row)
        return row

    @staticmethod
    def _validate_full(
        snapshot: FrozenAblationSnapshot,
        row: ProspectiveAblationDecision,
    ) -> None:
        if row.variant is not AblationVariant.FULL:
            raise ValueError("normal shadow evaluator must identify its result as the full variant")
        if row.snapshot_id != snapshot.snapshot_id:
            raise ValueError("normal shadow evaluator changed snapshot_id")
        if row.snapshot_payload_hash != snapshot.payload_hash:
            raise ValueError("normal shadow evaluator changed frozen payload identity")
        if row.policy_fingerprint != snapshot.policy_fingerprint:
            raise ValueError("normal shadow evaluator changed policy_fingerprint")
        if row.instrument != snapshot.instrument or row.signal_time != snapshot.signal_time:
            raise ValueError("normal shadow evaluator changed point-in-time market identity")

    @staticmethod
    def _validate_masked(
        request: ResearchAblationRequest,
        row: ProspectiveAblationDecision,
    ) -> None:
        if row.variant is not request.variant:
            raise ValueError(
                f"masked production evaluator returned {row.variant.value}; expected {request.variant.value}"
            )
        snapshot = request.snapshot
        if row.snapshot_id != snapshot.snapshot_id:
            raise ValueError("masked production evaluator changed snapshot_id")
        if row.snapshot_payload_hash != snapshot.payload_hash:
            raise ValueError("masked production evaluator changed frozen payload identity")
        if row.policy_fingerprint != snapshot.policy_fingerprint:
            raise ValueError("masked production evaluator changed policy_fingerprint")
        if row.instrument != snapshot.instrument or row.signal_time != snapshot.signal_time:
            raise ValueError("masked production evaluator changed point-in-time market identity")


def make_component_hooks(
    *,
    no_fundamentals: MaskedProductionEvaluator,
    no_flow: MaskedProductionEvaluator,
    no_session: MaskedProductionEvaluator,
    no_zone_quality: MaskedProductionEvaluator,
    no_retest: MaskedProductionEvaluator,
) -> Mapping[AblationVariant, ComponentAblationHook]:
    """Construct the complete required hook set with exact one-component declarations."""

    specs = (
        (AblationVariant.NO_FUNDAMENTALS, "fundamentals", no_fundamentals),
        (AblationVariant.NO_FLOW, "flow", no_flow),
        (AblationVariant.NO_SESSION, "session", no_session),
        (AblationVariant.NO_ZONE_QUALITY, "zone_quality", no_zone_quality),
        (AblationVariant.NO_RETEST, "retest", no_retest),
    )
    return {
        variant: ComponentAblationHook(variant=variant, component=component, evaluator=evaluator)
        for variant, component, evaluator in specs
    }
