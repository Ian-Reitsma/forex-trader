from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from enum import StrEnum

from forex_trader.domain.enums import Direction
from forex_trader.ingestion.providers import OrderFlowSnapshot


class ResearchFlowState(StrEnum):
    INELIGIBLE = "ineligible"
    WATCHING = "watching"
    ARMED = "armed"
    CONFIRMED = "confirmed"


@dataclass(frozen=True, slots=True)
class ResearchFlowSignal:
    strategy: str
    state: ResearchFlowState
    direction: Direction
    confidence: Decimal
    source: str | None
    reasons: tuple[str, ...]

    @property
    def executable(self) -> bool:
        """Research signals intentionally have no broker authority."""

        return False


def _centralized_flow_eligible(
    snapshot: OrderFlowSnapshot | None,
    *,
    minimum_confidence: Decimal,
) -> tuple[bool, tuple[str, ...]]:
    if snapshot is None:
        return False, ("institutional flow snapshot unavailable",)
    if snapshot.source.strip().lower() in {"", "none", "broker_tick_proxy", "spot_tick_proxy"}:
        return False, ("centralized institutional flow source required",)
    if snapshot.directional_pressure is None:
        return False, ("normalized directional pressure unavailable",)
    if snapshot.confidence < minimum_confidence:
        return False, (f"flow confidence {snapshot.confidence}<{minimum_confidence}",)
    return True, ()


@dataclass(frozen=True, slots=True)
class FlowDivergenceResearchPolicy:
    minimum_flow_pressure: Decimal = Decimal("0.35")
    minimum_confidence: Decimal = Decimal("0.60")
    minimum_price_move_pips: Decimal = Decimal("2")

    def evaluate(
        self,
        snapshot: OrderFlowSnapshot | None,
        *,
        price_change: Decimal,
        pip_size: Decimal,
        at_key_location: bool,
        structure_shift: bool,
    ) -> ResearchFlowSignal:
        if pip_size <= 0:
            raise ValueError("pip_size must be positive")
        eligible, reasons = _centralized_flow_eligible(snapshot, minimum_confidence=self.minimum_confidence)
        if not eligible or snapshot is None or snapshot.directional_pressure is None:
            return ResearchFlowSignal(
                "flow_divergence",
                ResearchFlowState.INELIGIBLE,
                Direction.FLAT,
                Decimal("0"),
                None if snapshot is None else snapshot.source,
                reasons,
            )
        pressure = snapshot.directional_pressure
        price_pips = price_change / pip_size
        bullish = price_pips <= -self.minimum_price_move_pips and pressure >= self.minimum_flow_pressure
        bearish = price_pips >= self.minimum_price_move_pips and pressure <= -self.minimum_flow_pressure
        if not bullish and not bearish:
            return ResearchFlowSignal(
                "flow_divergence",
                ResearchFlowState.WATCHING,
                Direction.FLAT,
                snapshot.confidence,
                snapshot.source,
                (f"no qualifying price/flow divergence: price={price_pips:.2f}p pressure={pressure}",),
            )
        direction = Direction.LONG if bullish else Direction.SHORT
        state = ResearchFlowState.ARMED if at_key_location else ResearchFlowState.WATCHING
        detail = [
            f"opposing price/flow divergence: price={price_pips:.2f}p pressure={pressure}",
            "key location confirmed" if at_key_location else "waiting for key location",
        ]
        if at_key_location and structure_shift:
            state = ResearchFlowState.CONFIRMED
            detail.append("structure shift confirmed")
        elif at_key_location:
            detail.append("waiting for structure shift")
        return ResearchFlowSignal(
            "flow_divergence",
            state,
            direction,
            snapshot.confidence,
            snapshot.source,
            tuple(detail),
        )


@dataclass(frozen=True, slots=True)
class VwapRepositioningResearchPolicy:
    minimum_flow_pressure: Decimal = Decimal("0.25")
    minimum_confidence: Decimal = Decimal("0.60")
    minimum_cross_distance_pips: Decimal = Decimal("0.5")

    def evaluate(
        self,
        snapshot: OrderFlowSnapshot | None,
        *,
        previous_price: Decimal,
        current_price: Decimal,
        pip_size: Decimal,
        structure_shift: bool,
    ) -> ResearchFlowSignal:
        if pip_size <= 0:
            raise ValueError("pip_size must be positive")
        eligible, reasons = _centralized_flow_eligible(snapshot, minimum_confidence=self.minimum_confidence)
        if not eligible or snapshot is None or snapshot.directional_pressure is None:
            return ResearchFlowSignal(
                "vwap_repositioning",
                ResearchFlowState.INELIGIBLE,
                Direction.FLAT,
                Decimal("0"),
                None if snapshot is None else snapshot.source,
                reasons,
            )
        if snapshot.vwap is None:
            return ResearchFlowSignal(
                "vwap_repositioning",
                ResearchFlowState.INELIGIBLE,
                Direction.FLAT,
                snapshot.confidence,
                snapshot.source,
                ("centralized VWAP unavailable",),
            )
        vwap = snapshot.vwap
        threshold = pip_size * self.minimum_cross_distance_pips
        reclaimed = previous_price < vwap - threshold and current_price > vwap + threshold
        lost = previous_price > vwap + threshold and current_price < vwap - threshold
        pressure = snapshot.directional_pressure
        long_aligned = reclaimed and pressure >= self.minimum_flow_pressure
        short_aligned = lost and pressure <= -self.minimum_flow_pressure
        if not reclaimed and not lost:
            return ResearchFlowSignal(
                "vwap_repositioning",
                ResearchFlowState.WATCHING,
                Direction.FLAT,
                snapshot.confidence,
                snapshot.source,
                ("price has not decisively repositioned across centralized VWAP",),
            )
        if not long_aligned and not short_aligned:
            return ResearchFlowSignal(
                "vwap_repositioning",
                ResearchFlowState.ARMED,
                Direction.LONG if reclaimed else Direction.SHORT,
                snapshot.confidence,
                snapshot.source,
                ("VWAP cross observed but institutional flow is not directionally aligned",),
            )
        direction = Direction.LONG if long_aligned else Direction.SHORT
        state = ResearchFlowState.CONFIRMED if structure_shift else ResearchFlowState.ARMED
        return ResearchFlowSignal(
            "vwap_repositioning",
            state,
            direction,
            snapshot.confidence,
            snapshot.source,
            (
                "decisive centralized VWAP repositioning",
                f"flow pressure={pressure}",
                "structure shift confirmed" if structure_shift else "waiting for structure shift",
            ),
        )
