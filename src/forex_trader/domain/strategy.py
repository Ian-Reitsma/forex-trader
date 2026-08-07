from __future__ import annotations

import hashlib
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
        minimum_score: Decimal = Decimal("0.68"),
        minimum_fundamental_confidence: Decimal = Decimal("0.50"),
        maximum_spread_pips: Decimal = Decimal("2.0"),
        maximum_quote_signal_gap_seconds: int = 900,
        minimum_reward_risk: Decimal = Decimal("1.75"),
        require_fundamentals: bool = True,
        require_liquidity_sweep: bool = True,
        require_displacement: bool = True,
        maximum_fundamental_conflict: Decimal = Decimal("0.05"),
    ) -> None:
        if not Decimal("0") <= minimum_score <= Decimal("1"):
            raise ValueError("minimum_score must be between 0 and 1")
        if maximum_spread_pips <= 0:
            raise ValueError("maximum_spread_pips must be positive")
        self.minimum_score = minimum_score
        self.minimum_fundamental_confidence = minimum_fundamental_confidence
        self.maximum_spread_pips = maximum_spread_pips
        self.maximum_quote_signal_gap_seconds = maximum_quote_signal_gap_seconds
        self.minimum_reward_risk = minimum_reward_risk
        self.require_fundamentals = require_fundamentals
        self.require_liquidity_sweep = require_liquidity_sweep
        self.require_displacement = require_displacement
        self.maximum_fundamental_conflict = maximum_fundamental_conflict

    def evaluate(
        self,
        technical: TechnicalAssessment,
        fundamental: FundamentalAssessment,
        quote: Quote,
        *,
        maximum_spread_pips: Decimal | None = None,
    ) -> TradeCandidate:
        reasons = [*technical.reasons, *fundamental.reasons]
        spread_pips = quote.spread / pip_size(technical.instrument)
        spread_limit = self.maximum_spread_pips if maximum_spread_pips is None else maximum_spread_pips
        if spread_limit <= 0:
            raise ValueError("maximum_spread_pips override must be positive")
        signal_gap = (quote.time - technical.signal_time).total_seconds()

        if technical.direction is Direction.FLAT:
            return self._abstain(technical, fundamental, "technical direction is flat", reasons)
        if technical.stop_reference is None or technical.take_profit_reference is None:
            return self._abstain(technical, fundamental, "technical protection levels are unavailable", reasons)
        if signal_gap < 0 or signal_gap > self.maximum_quote_signal_gap_seconds:
            return self._abstain(
                technical,
                fundamental,
                f"quote/signal gap {signal_gap:.0f}s is outside the permitted window",
                reasons,
            )
        if spread_pips > spread_limit:
            return self._abstain(
                technical,
                fundamental,
                f"spread {spread_pips:.2f} pips exceeds maximum {spread_limit}",
                reasons,
            )
        if self.require_liquidity_sweep and not technical.liquidity_sweep:
            return self._abstain(technical, fundamental, "liquidity sweep confirmation is missing", reasons)
        if self.require_displacement and not technical.displacement:
            return self._abstain(technical, fundamental, "directional displacement confirmation is missing", reasons)
        if self.require_fundamentals and fundamental.confidence < self.minimum_fundamental_confidence:
            return self._abstain(technical, fundamental, "fundamental confidence is insufficient", reasons)

        entry = quote.ask if technical.direction is Direction.LONG else quote.bid
        stop_distance = abs(entry - technical.stop_reference)
        reward_distance = abs(technical.take_profit_reference - entry)
        reward_risk = Decimal("0") if stop_distance == 0 else reward_distance / stop_distance
        if reward_risk < self.minimum_reward_risk:
            return self._abstain(
                technical,
                fundamental,
                f"executable reward/risk {reward_risk:.2f} is below {self.minimum_reward_risk}",
                reasons,
            )

        aligned = (
            technical.direction is Direction.LONG
            and fundamental.differential >= -self.maximum_fundamental_conflict
        ) or (
            technical.direction is Direction.SHORT
            and fundamental.differential <= self.maximum_fundamental_conflict
        )
        if not aligned:
            return self._abstain(technical, fundamental, "fundamental context conflicts with direction", reasons)

        directional_fundamental = (
            fundamental.differential if technical.direction is Direction.LONG else -fundamental.differential
        )
        normalized_fundamental = max(
            Decimal("0"), min(Decimal("1"), (directional_fundamental + Decimal("1")) / Decimal("2"))
        )
        score = technical.score * Decimal("0.75") + normalized_fundamental * Decimal("0.25")
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

        execution_key = _execution_key(technical.instrument, technical.direction, technical.signal_time.isoformat())
        reasons.extend(
            (
                f"executable reward/risk={reward_risk:.2f}",
                f"combined score {score:.3f} passed",
            )
        )
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
            signal_time=technical.signal_time,
            execution_key=execution_key,
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
            signal_time=technical.signal_time,
            execution_key="",
        )


def _execution_key(instrument: str, direction: Direction, signal_time: str) -> str:
    digest = hashlib.sha256(f"{instrument}|{direction.value}|{signal_time}".encode()).hexdigest()[:24]
    return f"ft-{instrument.lower()}-{digest}"
