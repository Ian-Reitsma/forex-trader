from __future__ import annotations

from decimal import Decimal

from forex_trader.domain.context import ConfirmationCategory, ConfirmationEvidence
from forex_trader.domain.decision_components import DecisionComponentPolicy, PRODUCTION_DECISION_COMPONENTS
from forex_trader.domain.enums import Direction
from forex_trader.domain.models import FundamentalAssessment, Quote, TechnicalAssessment


_NON_INSTITUTIONAL_FLOW_SOURCES = frozenset({"", "none", "broker_tick_proxy"})


def _pressure_aligns(direction: Direction, pressure: Decimal) -> bool:
    if direction is Direction.LONG:
        return pressure >= Decimal("0.20")
    if direction is Direction.SHORT:
        return pressure <= Decimal("-0.20")
    return False


def confirmation_evidence_for_components(
    technical: TechnicalAssessment,
    fundamental: FundamentalAssessment,
    quote: Quote,
    *,
    spread_limit_pips: Decimal,
    pip_size: Decimal,
    components: DecisionComponentPolicy = PRODUCTION_DECISION_COMPONENTS,
    cross_asset_alignment: Decimal = Decimal("0"),
    cross_asset_source_ids: tuple[str, ...] = (),
    institutional_flow_pressure: Decimal | None = None,
    institutional_flow_source: str | None = None,
    institutional_flow_confidence: Decimal = Decimal("0"),
) -> ConfirmationEvidence:
    """Build independent confirmation evidence without double-counting local proxies.

    Broker tick activity can remain a technical feature, but it is not an independent
    institutional-flow source. An external flow snapshot counts only when its normalized
    pressure agrees with the trade direction and the provider confidence is sufficient.
    """

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

    technical_flow_source = technical.flow_source.strip().lower()
    if (
        components.flow
        and technical_flow_source not in _NON_INSTITUTIONAL_FLOW_SOURCES
        and _pressure_aligns(technical.direction, technical.flow_pressure)
    ):
        categories.add(ConfirmationCategory.FLOW)
        sources.add(technical.flow_source)
        reasons.append(f"institutional technical flow pressure={technical.flow_pressure}")

    if (
        components.flow
        and institutional_flow_source
        and institutional_flow_source.strip().lower() not in _NON_INSTITUTIONAL_FLOW_SOURCES
        and institutional_flow_pressure is not None
        and institutional_flow_confidence >= Decimal("0.50")
        and _pressure_aligns(technical.direction, institutional_flow_pressure)
    ):
        categories.add(ConfirmationCategory.FLOW)
        sources.add(institutional_flow_source)
        reasons.append(
            "external institutional flow "
            f"pressure={institutional_flow_pressure} confidence={institutional_flow_confidence}"
        )

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

    cross_asset_directional = (
        cross_asset_alignment
        if technical.direction is Direction.LONG
        else -cross_asset_alignment
        if technical.direction is Direction.SHORT
        else Decimal("0")
    )
    if cross_asset_directional >= Decimal("0.25"):
        categories.add(ConfirmationCategory.CROSS_ASSET)
        if cross_asset_source_ids:
            sources.update(cross_asset_source_ids)
        else:
            sources.add("cross_asset")
        reasons.append(f"cross-asset alignment={cross_asset_alignment}")

    spread_pips = quote.spread / pip_size
    if spread_pips <= spread_limit_pips:
        categories.add(ConfirmationCategory.EXECUTION)
        sources.add("broker_quote")
        reasons.append(f"spread={spread_pips:.3f}p")
    return ConfirmationEvidence(frozenset(categories), frozenset(sources), tuple(reasons))
