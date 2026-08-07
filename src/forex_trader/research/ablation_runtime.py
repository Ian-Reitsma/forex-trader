from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Mapping

from forex_trader.domain.enums import OperatingMode
from forex_trader.research.ablations import (
    AblationVariant,
    FrozenAblationSnapshot,
    ProspectiveAblationCollector,
    ProspectiveAblationDecision,
)


@dataclass(frozen=True, slots=True)
class ResearchFeatureMask:
    fundamentals: bool = True
    flow: bool = True
    session: bool = True
    zone_quality: bool = True
    retest: bool = True

    @property
    def disabled_components(self) -> tuple[str, ...]:
        values = (
            ("fundamentals", self.fundamentals),
            ("flow", self.flow),
            ("session", self.session),
            ("zone_quality", self.zone_quality),
            ("retest", self.retest),
        )
        return tuple(name for name, enabled in values if not enabled)


FEATURE_MASKS: Mapping[AblationVariant, ResearchFeatureMask] = {
    AblationVariant.FULL: ResearchFeatureMask(),
    AblationVariant.NO_FUNDAMENTALS: ResearchFeatureMask(fundamentals=False),
    AblationVariant.NO_FLOW: ResearchFeatureMask(flow=False),
    AblationVariant.NO_SESSION: ResearchFeatureMask(session=False),
    AblationVariant.NO_ZONE_QUALITY: ResearchFeatureMask(zone_quality=False),
    AblationVariant.NO_RETEST: ResearchFeatureMask(retest=False),
}


@dataclass(frozen=True, slots=True)
class ResearchAblationRequest:
    snapshot: FrozenAblationSnapshot
    variant: AblationVariant
    mask: ResearchFeatureMask
    execution_enabled: bool = False

    def __post_init__(self) -> None:
        if self.execution_enabled:
            raise ValueError("research ablation requests cannot enable execution")
        expected = FEATURE_MASKS.get(self.variant)
        if expected is None or expected != self.mask:
            raise ValueError(f"feature mask does not match declared variant {self.variant.value}")


MaskedAblationEvaluator = Callable[[ResearchAblationRequest], ProspectiveAblationDecision]


class ShadowAblationRuntime:
    """Translate prospective variants into explicit research-only component masks.

    This runtime does not know how to bypass a production gate by itself. A concrete decision
    adapter must consume `ResearchAblationRequest` and rerun the actual decision path against
    the supplied frozen snapshot. Construction fails unless the caller is in SHADOW mode with
    paper-order writes disabled, creating a hard authority boundary before evaluator code runs.
    """

    def __init__(
        self,
        evaluator: MaskedAblationEvaluator,
        *,
        mode: OperatingMode,
        enable_paper_orders: bool,
    ) -> None:
        if mode is not OperatingMode.SHADOW:
            raise ValueError("prospective ablation runtime is restricted to shadow mode")
        if enable_paper_orders:
            raise ValueError("prospective ablation runtime cannot enable paper broker writes")
        self._evaluator = evaluator
        self._collector = ProspectiveAblationCollector(self._evaluate_variant)

    def collect(self, snapshot: FrozenAblationSnapshot) -> tuple[ProspectiveAblationDecision, ...]:
        return self._collector.collect(snapshot)

    def _evaluate_variant(
        self,
        snapshot: FrozenAblationSnapshot,
        variant: AblationVariant,
    ) -> ProspectiveAblationDecision:
        request = ResearchAblationRequest(
            snapshot=snapshot,
            variant=variant,
            mask=FEATURE_MASKS[variant],
            execution_enabled=False,
        )
        return self._evaluator(request)
