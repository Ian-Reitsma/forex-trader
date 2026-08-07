from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class DecisionComponentPolicy:
    """Select which evidence components may affect a signal decision.

    The all-True default is the production policy. Research-only callers may disable exactly
    one component for a paired ablation, but ordinary runtime code does not need to know that
    such experiments exist.
    """

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

    @property
    def is_production_default(self) -> bool:
        return not self.disabled_components


PRODUCTION_DECISION_COMPONENTS = DecisionComponentPolicy()
