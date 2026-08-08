from __future__ import annotations

from dataclasses import replace
from decimal import Decimal

from forex_trader.domain.component_confirmation import confirmation_evidence_for_components
from forex_trader.domain.context import (
    ConfirmationCategory,
    FlowRequirement,
    PolicyAuthority,
    StrategyPolicyRegistry,
    classify_regime,
)
from forex_trader.domain.decision_components import DecisionComponentPolicy, PRODUCTION_DECISION_COMPONENTS
from forex_trader.domain.enums import DecisionDisposition
from forex_trader.domain.instruments import pip_size_for
from forex_trader.domain.models import FundamentalAssessment, Quote, TechnicalAssessment, TradeCandidate
from forex_trader.domain.policy_registry import CompleteStrategyPolicyRegistry
from forex_trader.domain.sessions import SessionPhase, classify_phase
from forex_trader.domain.strategy import SignalFusionPolicy


class RegimeAwareSignalFusionPolicy(SignalFusionPolicy):
    """Preserve the proven sweep/reclaim policy while enforcing evidence independence.

    The base policy remains responsible for structural eligibility and fundamental conflict.
    This extension adds explicit regime/policy identity and independent evidence accounting.
    It does not treat the quality score as a probability and does not grant non-sweep
    strategy families Practice authority.
    """

    def __init__(
        self,
        *,
        minimum_score: Decimal = Decimal("0.68"),
        minimum_fundamental_confidence: Decimal = Decimal("0.50"),
        maximum_spread_pips: Decimal = Decimal("2.0"),
        maximum_quote_signal_gap_seconds: int = 420,
        minimum_reward_risk: Decimal = Decimal("1.35"),
        require_fundamentals: bool = True,
        require_liquidity_sweep: bool = True,
        require_displacement: bool = False,
        require_structure_shift: bool = True,
        require_entry_confirmed: bool = True,
        minimum_location_score: Decimal = Decimal("0.28"),
        maximum_fundamental_conflict: Decimal = Decimal("0.08"),
        minimum_independent_confirmations: int = 2,
        minimum_independent_sources: int = 2,
        registry: StrategyPolicyRegistry | None = None,
    ) -> None:
        super().__init__(
            minimum_score=minimum_score,
            minimum_fundamental_confidence=minimum_fundamental_confidence,
            maximum_spread_pips=maximum_spread_pips,
            maximum_quote_signal_gap_seconds=maximum_quote_signal_gap_seconds,
            minimum_reward_risk=minimum_reward_risk,
            require_fundamentals=require_fundamentals,
            require_liquidity_sweep=require_liquidity_sweep,
            require_displacement=require_displacement,
            require_structure_shift=require_structure_shift,
            require_entry_confirmed=require_entry_confirmed,
            minimum_location_score=minimum_location_score,
            maximum_fundamental_conflict=maximum_fundamental_conflict,
        )
        if minimum_independent_confirmations < 1:
            raise ValueError("minimum_independent_confirmations must be positive")
        if minimum_independent_sources < 1:
            raise ValueError("minimum_independent_sources must be positive")
        self.minimum_independent_confirmations = minimum_independent_confirmations
        self.minimum_independent_sources = minimum_independent_sources
        self.registry = registry or CompleteStrategyPolicyRegistry()

    def evaluate(
        self,
        technical: TechnicalAssessment,
        fundamental: FundamentalAssessment,
        quote: Quote,
        *,
        maximum_spread_pips: Decimal | None = None,
        components: DecisionComponentPolicy = PRODUCTION_DECISION_COMPONENTS,
        cross_asset_alignment: Decimal = Decimal("0"),
        cross_asset_source_ids: tuple[str, ...] = (),
        institutional_flow_pressure: Decimal | None = None,
        institutional_flow_source: str | None = None,
        institutional_flow_confidence: Decimal = Decimal("0"),
    ) -> TradeCandidate:
        candidate = super().evaluate(
            technical,
            fundamental,
            quote,
            maximum_spread_pips=maximum_spread_pips,
        )
        spread_limit = self.maximum_spread_pips if maximum_spread_pips is None else maximum_spread_pips
        phase = classify_phase(quote.time) if components.session else SessionPhase.OFF_HOURS
        regime = classify_regime(technical, phase=phase)
        policy = self.registry.select(regime.regime, maximum_authority=PolicyAuthority.PRACTICE)
        confirmations = confirmation_evidence_for_components(
            technical,
            fundamental,
            quote,
            spread_limit_pips=spread_limit,
            pip_size=pip_size_for(technical.instrument),
            components=components,
            cross_asset_alignment=cross_asset_alignment,
            cross_asset_source_ids=cross_asset_source_ids,
            institutional_flow_pressure=institutional_flow_pressure,
            institutional_flow_source=institutional_flow_source,
            institutional_flow_confidence=institutional_flow_confidence,
        )
        evidence = {
            **candidate.evidence,
            "regime": regime.regime.value,
            "regime_confidence": regime.confidence,
            "regime_reasons": regime.reasons,
            "selected_policy": None if policy is None else f"{policy.name}:{policy.version}",
            "policy_authority": None if policy is None else policy.authority.value,
            "flow_requirement": None if policy is None else policy.flow_requirement.value,
            "cross_asset_alignment": cross_asset_alignment,
            "institutional_flow_source": institutional_flow_source,
            "institutional_flow_pressure": institutional_flow_pressure,
            "institutional_flow_confidence": institutional_flow_confidence,
            "confirmation_categories": tuple(sorted(item.value for item in confirmations.categories)),
            "confirmation_source_ids": tuple(sorted(confirmations.source_ids)),
            "independent_confirmation_count": confirmations.independent_confirmation_count,
            "independent_source_count": confirmations.independent_source_count,
            "confirmation_reasons": confirmations.reasons,
        }
        if components.disabled_components:
            evidence["decision_components_disabled"] = components.disabled_components
        candidate = replace(candidate, evidence=evidence)
        if candidate.disposition is not DecisionDisposition.TRADE:
            return candidate
        if policy is None:
            return replace(
                candidate,
                disposition=DecisionDisposition.ABSTAIN,
                rejection_code="REGIME_NO_PRACTICE_POLICY",
                entry_price=None,
                stop_loss=None,
                take_profit=None,
                reasons=(*candidate.reasons, f"REGIME_NO_PRACTICE_POLICY: regime={regime.regime.value}"),
            )
        if policy.flow_requirement is FlowRequirement.REQUIRED and ConfirmationCategory.FLOW not in confirmations.categories:
            return replace(
                candidate,
                disposition=DecisionDisposition.ABSTAIN,
                rejection_code="INSTITUTIONAL_FLOW_REQUIRED",
                entry_price=None,
                stop_loss=None,
                take_profit=None,
                reasons=(
                    *candidate.reasons,
                    f"INSTITUTIONAL_FLOW_REQUIRED: {policy.name}:{policy.version} requires healthy independent flow",
                ),
            )
        if policy.name != "sweep_reclaim":
            return replace(
                candidate,
                disposition=DecisionDisposition.ABSTAIN,
                rejection_code="POLICY_NOT_PRACTICE_AUTHORIZED",
                entry_price=None,
                stop_loss=None,
                take_profit=None,
                reasons=(*candidate.reasons, f"POLICY_NOT_PRACTICE_AUTHORIZED: {policy.name}:{policy.version}"),
            )
        if not confirmations.satisfies(self.minimum_independent_confirmations, self.minimum_independent_sources):
            return replace(
                candidate,
                disposition=DecisionDisposition.ABSTAIN,
                rejection_code="INDEPENDENT_CONFIRMATION_MISSING",
                entry_price=None,
                stop_loss=None,
                take_profit=None,
                reasons=(
                    *candidate.reasons,
                    "INDEPENDENT_CONFIRMATION_MISSING: "
                    f"categories={confirmations.independent_confirmation_count}/{self.minimum_independent_confirmations}, "
                    f"sources={confirmations.independent_source_count}/{self.minimum_independent_sources}",
                ),
            )
        return candidate
