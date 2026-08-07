from __future__ import annotations

from decimal import Decimal
from uuid import uuid4

from forex_trader.domain.enums import DecisionDisposition, Direction
from forex_trader.domain.models import (
    FundamentalAssessment,
    Quote,
    TechnicalAssessment,
    TradeCandidate,
)
from forex_trader.domain.technicals import pip_size


class SignalFusionPolicy:
    def __init__(
        self,
        *,
        minimum_score: Decimal = Decimal("0.62"),
        minimum_fundamental_confidence: Decimal = Decimal("0.50"),
        maximum_spread_pips: Decimal = Decimal("2.5"),
        require_fundamentals: bool = True,
    ) -> None:
        self.minimum_score = minimum_score
        self.minimum_fundamental_confidence = minimum_fundamental_confidence
        self.maximum_spread_pips = maximum_spread_pips
        self.require_fundamentals = require_fundamentals

    def evaluate(
        self,
        technical: TechnicalAssessment,
        fundamental: FundamentalAssessment,
        quote: Quote,
    ) -> TradeCandidate:
        reasons = [*technical.reasons, *fundamental.reasons]
        spread_pips = quote.spread / pip_size(technical.instrument)
        if technical.direction is Direction.FLAT:
            return self._abstain(technical, fundamental, "technical direction is flat", reasons)
        if technical.stop_reference is None or technical.take_profit_reference is None:
            return self._abstain(technical, fundamental, "technical protection levels are unavailable", reasons)
        if spread_pips > self.maximum_spread_pips:
            return self._abstain(
                technical,
                fundamental,
                f"spread {spread_pips:.2f} pips exceeds maximum {self.maximum_spread_pips}",
                reasons,
            )
        if self.require_fundamentals and fundamental.confidence < self.minimum_fundamental_confidence:
            return self._abstain(technical, fundamental, "fundamental confidence is insufficient", reasons)

        aligned = (
            technical.direction is Direction.LONG and fundamental.differential >= Decimal("-0.10")
        ) or (
            technical.direction is Direction.SHORT and fundamental.differential <= Decimal("0.10")
        )
        if not aligned:
            return self._abstain(technical, fundamental, "fundamental context conflicts with direction", reasons)

        directional_fundamental = (
            fundamental.differential if technical.direction is Direction.LONG else -fundamental.differential
        )
        normalized_fundamental = max(
            Decimal("0"), min(Decimal("1"), (directional_fundamental + Decimal("1")) / Decimal("2"))
        )
        score = technical.score * Decimal("0.65") + normalized_fundamental * Decimal("0.35")
        score -= min(Decimal("0.15"), spread_pips / Decimal("100"))
        score = max(Decimal("0"), min(Decimal("1"), score))
        if score < self.minimum_score:
            return self._abstain(
                technical,
                fundamental,
                f"combined score {score:.3f} is below {self.minimum_score}",
                reasons,
                score=score,
            )

        entry = quote.ask if technical.direction is Direction.LONG else quote.bid
        reasons.append(f"combined score {score:.3f} passed")
        return TradeCandidate(
            candidate_id=uuid4(),
            instrument=technical.instrument,
            direction=technical.direction,
            disposition=DecisionDisposition.TRADE,
            score=score,
            entry_price=entry,
            stop_loss=technical.stop_reference,
            take_profit=technical.take_profit_reference,
            technical_score=technical.score,
            fundamental_score=normalized_fundamental,
            reasons=tuple(reasons),
        )

    def _abstain(
        self,
        technical: TechnicalAssessment,
        fundamental: FundamentalAssessment,
        reason: str,
        reasons: list[str],
        *,
        score: Decimal = Decimal("0"),
    ) -> TradeCandidate:
        reasons.append(reason)
        return TradeCandidate(
            candidate_id=uuid4(),
            instrument=technical.instrument,
            direction=technical.direction,
            disposition=DecisionDisposition.ABSTAIN,
            score=score,
            entry_price=None,
            stop_loss=None,
            take_profit=None,
            technical_score=technical.score,
            fundamental_score=fundamental.differential,
            reasons=tuple(reasons),
        )
