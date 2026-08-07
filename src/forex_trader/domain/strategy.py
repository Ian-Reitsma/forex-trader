from __future__ import annotations

import hashlib
from dataclasses import replace
from datetime import timedelta
from decimal import Decimal
from uuid import uuid4

from forex_trader.domain.enums import DecisionDisposition, Direction
from forex_trader.domain.instruments import pip_size_for
from forex_trader.domain.models import FundamentalAssessment, Quote, TechnicalAssessment, TradeCandidate
from forex_trader.domain.setup import SetupState


class SignalFusionPolicy:
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
        self.require_structure_shift = require_structure_shift
        self.require_entry_confirmed = require_entry_confirmed
        self.minimum_location_score = minimum_location_score
        self.maximum_fundamental_conflict = maximum_fundamental_conflict

    def evaluate(
        self,
        technical: TechnicalAssessment,
        fundamental: FundamentalAssessment,
        quote: Quote,
        *,
        maximum_spread_pips: Decimal | None = None,
    ) -> TradeCandidate:
        _validate_instruments(technical, fundamental, quote)
        reasons = [*technical.reasons, *fundamental.reasons]
        spread_limit = self.maximum_spread_pips if maximum_spread_pips is None else maximum_spread_pips
        if spread_limit <= 0:
            raise ValueError("maximum_spread_pips override must be positive")
        spread_pips = quote.spread / pip_size_for(technical.instrument)
        signal_gap = (quote.time - technical.signal_time).total_seconds()

        if technical.direction is Direction.FLAT:
            return self._abstain(technical, fundamental, "TECHNICAL_FLAT", "technical direction is flat", reasons)
        if technical.stop_reference is None or technical.take_profit_reference is None:
            return self._abstain(technical, fundamental, "NO_STRUCTURAL_TARGET", "structural protection/target is unavailable", reasons)
        if signal_gap < 0 or signal_gap > self.maximum_quote_signal_gap_seconds:
            return self._abstain(technical, fundamental, "QUOTE_STALE", f"quote/signal gap {signal_gap:.0f}s is outside the permitted window", reasons)
        if spread_pips > spread_limit:
            return self._abstain(technical, fundamental, "SPREAD_TOO_WIDE", f"spread {spread_pips:.2f} pips exceeds maximum {spread_limit}", reasons)
        if self.require_liquidity_sweep and not technical.liquidity_sweep:
            return self._abstain(technical, fundamental, "NO_DECLARED_LIQUIDITY_SWEEP", "declared liquidity has not been swept/reclaimed", reasons)
        if self.require_structure_shift and not technical.structure_shift:
            return self._abstain(technical, fundamental, "NO_STRUCTURE_SHIFT", "post-sweep market-structure confirmation is missing", reasons)
        if self.require_entry_confirmed and technical.setup_state != SetupState.ENTRY_CONFIRMED.value:
            return self._abstain(technical, fundamental, "SETUP_NOT_ENTRY_READY", f"setup state is {technical.setup_state}, not entry_confirmed", reasons)
        if technical.location_score < self.minimum_location_score:
            return self._abstain(technical, fundamental, "LOCATION_LOW_QUALITY", f"location score {technical.location_score:.2f} is below {self.minimum_location_score}", reasons)
        if self.require_displacement and not technical.displacement:
            return self._abstain(technical, fundamental, "NO_DISPLACEMENT", "directional displacement confirmation is missing", reasons)
        if self.require_fundamentals and fundamental.confidence < self.minimum_fundamental_confidence:
            return self._abstain(technical, fundamental, "FUNDAMENTAL_UNCALIBRATED", "fundamental confidence is insufficient", reasons)

        entry = quote.ask if technical.direction is Direction.LONG else quote.bid
        stop_distance = abs(entry - technical.stop_reference)
        reward_distance = abs(technical.take_profit_reference - entry)
        reward_risk = Decimal("0") if stop_distance == 0 else reward_distance / stop_distance
        if reward_risk < self.minimum_reward_risk:
            return self._abstain(technical, fundamental, "INSUFFICIENT_NET_REWARD", f"executable structural reward/risk {reward_risk:.2f} is below {self.minimum_reward_risk}", reasons)

        directional_fundamental = fundamental.differential if technical.direction is Direction.LONG else -fundamental.differential
        if self.require_fundamentals and directional_fundamental < -self.maximum_fundamental_conflict:
            return self._abstain(technical, fundamental, "FUNDAMENTAL_CONFLICT", "fundamental context conflicts with direction", reasons)

        if self.require_fundamentals:
            normalized = max(Decimal("0"), min(Decimal("1"), (directional_fundamental + Decimal("1")) / Decimal("2")))
            effective_fundamental = normalized * max(Decimal("0"), min(Decimal("1"), fundamental.confidence))
            score = technical.score * Decimal("0.80") + effective_fundamental * Decimal("0.20")
        else:
            effective_fundamental = Decimal("0")
            score = technical.score
        score -= min(Decimal("0.08"), (spread_pips / spread_limit) * Decimal("0.04"))
        score = max(Decimal("0"), min(Decimal("1"), score))
        if score < self.minimum_score:
            return self._abstain(technical, fundamental, "SCORE_BELOW_POLICY", f"combined quality {score:.3f} is below {self.minimum_score}", reasons, score=score)

        execution_key = _execution_key(
            technical.instrument,
            technical.direction,
            technical.signal_time.isoformat(),
            technical.setup_family,
            technical.zone_id or "no-zone",
        )
        reasons.extend((f"executable structural reward/risk={reward_risk:.2f}", f"combined quality {score:.3f} passed"))
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
            fundamental_score=effective_fundamental,
            fundamental_confidence=fundamental.confidence,
            reasons=tuple(reasons),
            signal_time=technical.signal_time,
            execution_key=execution_key,
            setup_family=technical.setup_family,
            setup_state=technical.setup_state,
            evidence={
                "raw_fundamental_differential": fundamental.differential,
                "zone_id": technical.zone_id,
                "zone_quality": technical.zone_quality,
                "liquidity_kind": technical.liquidity_kind,
                "liquidity_price": technical.liquidity_price,
                "liquidity_strength": technical.liquidity_strength,
                "location_score": technical.location_score,
                "structure_shift": technical.structure_shift,
                "retest_confirmed": technical.retest_confirmed,
                "flow_source": technical.flow_source,
                "flow_pressure": technical.flow_pressure,
            },
            expires_at=technical.signal_time + timedelta(minutes=10),
        )

    def revalidate_execution(
        self,
        candidate: TradeCandidate,
        quote: Quote,
        *,
        maximum_spread_pips: Decimal | None = None,
    ) -> TradeCandidate:
        if candidate.disposition is not DecisionDisposition.TRADE:
            return candidate
        if candidate.expires_at is not None and quote.time > candidate.expires_at:
            return replace(candidate, disposition=DecisionDisposition.ABSTAIN, rejection_code="CANDIDATE_EXPIRED", reasons=(*candidate.reasons, "candidate expired before execution"), entry_price=None, stop_loss=None, take_profit=None)
        if quote.instrument.upper() != candidate.instrument.upper():
            raise ValueError("execution quote instrument does not match candidate")
        spread_limit = self.maximum_spread_pips if maximum_spread_pips is None else maximum_spread_pips
        spread_pips = quote.spread / pip_size_for(candidate.instrument)
        if spread_pips > spread_limit:
            return replace(candidate, disposition=DecisionDisposition.ABSTAIN, rejection_code="SPREAD_TOO_WIDE", reasons=(*candidate.reasons, f"send-time spread {spread_pips:.2f} pips exceeds {spread_limit}"), entry_price=None, stop_loss=None, take_profit=None)
        assert candidate.stop_loss is not None and candidate.take_profit is not None
        entry = quote.ask if candidate.direction is Direction.LONG else quote.bid
        if candidate.direction is Direction.LONG and not candidate.stop_loss < entry < candidate.take_profit:
            return replace(candidate, disposition=DecisionDisposition.ABSTAIN, rejection_code="LATE_ENTRY", reasons=(*candidate.reasons, "send-time price consumed the structural trade geometry"), entry_price=None, stop_loss=None, take_profit=None)
        if candidate.direction is Direction.SHORT and not candidate.take_profit < entry < candidate.stop_loss:
            return replace(candidate, disposition=DecisionDisposition.ABSTAIN, rejection_code="LATE_ENTRY", reasons=(*candidate.reasons, "send-time price consumed the structural trade geometry"), entry_price=None, stop_loss=None, take_profit=None)
        rr = abs(candidate.take_profit - entry) / abs(entry - candidate.stop_loss)
        if rr < self.minimum_reward_risk:
            return replace(candidate, disposition=DecisionDisposition.ABSTAIN, rejection_code="INSUFFICIENT_NET_REWARD", reasons=(*candidate.reasons, f"send-time reward/risk fell to {rr:.2f}"), entry_price=None, stop_loss=None, take_profit=None)
        return replace(candidate, entry_price=entry, reasons=(*candidate.reasons, f"send-time execution revalidated at {entry}"))

    def _abstain(
        self,
        technical: TechnicalAssessment,
        fundamental: FundamentalAssessment,
        code: str,
        reason: str,
        reasons: list[str],
        *,
        score: Decimal | None = None,
    ) -> TradeCandidate:
        reasons.append(f"{code}: {reason}")
        preserved_score = technical.score if score is None else score
        directional = fundamental.differential if technical.direction is Direction.LONG else -fundamental.differential if technical.direction is Direction.SHORT else Decimal("0")
        normalized = max(Decimal("0"), min(Decimal("1"), (directional + Decimal("1")) / Decimal("2")))
        effective_fundamental = normalized * max(Decimal("0"), min(Decimal("1"), fundamental.confidence))
        return TradeCandidate(
            candidate_id=uuid4(),
            instrument=technical.instrument,
            direction=technical.direction,
            disposition=DecisionDisposition.ABSTAIN,
            score=preserved_score,
            entry_price=None,
            stop_loss=None,
            take_profit=None,
            technical_score=technical.score,
            fundamental_score=effective_fundamental,
            fundamental_confidence=fundamental.confidence,
            reasons=tuple(reasons),
            signal_time=technical.signal_time,
            execution_key="",
            setup_family=technical.setup_family,
            setup_state=technical.setup_state,
            rejection_code=code,
            evidence={
                "raw_fundamental_differential": fundamental.differential,
                "zone_id": technical.zone_id,
                "zone_quality": technical.zone_quality,
                "liquidity_kind": technical.liquidity_kind,
                "liquidity_price": technical.liquidity_price,
                "location_score": technical.location_score,
                "structure_shift": technical.structure_shift,
            },
            expires_at=technical.signal_time + timedelta(minutes=10),
        )


def _validate_instruments(technical: TechnicalAssessment, fundamental: FundamentalAssessment, quote: Quote) -> None:
    expected = technical.instrument.upper()
    if fundamental.instrument.upper() != expected or quote.instrument.upper() != expected:
        raise ValueError("technical, fundamental and quote instruments must match")


def _execution_key(instrument: str, direction: Direction, signal_time: str, setup_family: str, location_id: str) -> str:
    digest = hashlib.sha256(f"{instrument}|{direction.value}|{signal_time}|{setup_family}|{location_id}".encode()).hexdigest()[:24]
    return f"ft-{instrument.lower()}-{digest}"
