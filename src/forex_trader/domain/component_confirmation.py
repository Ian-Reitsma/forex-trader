from __future__ import annotations

from decimal import Decimal

from forex_trader.domain.context import ConfirmationCategory, ConfirmationEvidence, confirmation_evidence
from forex_trader.domain.decision_components import DecisionComponentPolicy, PRODUCTION_DECISION_COMPONENTS
from forex_trader.domain.enums import Direction
from forex_trader.domain.models import FundamentalAssessment, Quote, TechnicalAssessment


def confirmation_evidence_for_components(
    technical: TechnicalAssessment,
    fundamental: FundamentalAssessment,
    quote: Quote,
    *,
    spread_limit_pips: Decimal,
    pip_size: Decimal,
    components: DecisionComponentPolicy = PRODUCTION_DECISION_COMPONENTS,
    cross_asset_alignment: Decimal = Decimal("0"),
) -> ConfirmationEvidence:
    """Return production confirmation evidence with optional component removal.

    The all-on path delegates to the established production helper exactly. Masked paths
    reconstruct the same category rules while omitting only disabled evidence families.
    """
    if components.is_production_default:
        return confirmation_evidence(
            technical,
            fundamental,
            quote,
            spread_limit_pips=spread_limit_pips,
            pip_size=pip_size,
            cross_asset_alignment=cross_asset_alignment,
        )

    categories: set[ConfirmationCategory] = set()
    sources: set[str] = set()
    reasons: list[str] = []
    price_confirmed = technical.structure_shift and (technical.retest_confirmed or not components.retest)
    if price_confirmed:
        categories.add(ConfirmationCategory.PRICE)
        sources.add("price")
        reasons.append(
            "price structure shift and retest confirmed"
            if components.retest
            else "price structure shift confirmed without retest requirement"
        )
    if components.flow and technical.flow_source not in {"", "none"} and abs(technical.flow_pressure) >= Decimal("0.20"):
        categories.add(ConfirmationCategory.FLOW)
        sources.add(technical.flow_source)
        reasons.append(f"flow pressure={technical.flow_pressure}")
    directional = (
        fundamental.differential
        if technical.direction is Direction.LONG
        else -fundamental.differential
        if technical.direction is Direction.SHORT
        else Decimal("0")
    )
    if components.fundamentals and fundamental.confidence >= Decimal("0.50") and directional >= Decimal("0"):
        categories.add(ConfirmationCategory.FUNDAMENTAL)
        sources.add("macro")
        reasons.append("fundamental context is non-conflicting with sufficient confidence")
    if cross_asset_alignment >= Decimal("0.25"):
        categories.add(ConfirmationCategory.CROSS_ASSET)
        sources.add("cross_asset")
        reasons.append(f"cross-asset alignment={cross_asset_alignment}")
    spread_pips = quote.spread / pip_size
    if spread_pips <= spread_limit_pips:
        categories.add(ConfirmationCategory.EXECUTION)
        sources.add("broker_quote")
        reasons.append(f"spread={spread_pips:.3f}p")
    return ConfirmationEvidence(frozenset(categories), frozenset(sources), tuple(reasons))
