from __future__ import annotations

import hashlib
import json
from dataclasses import replace
from decimal import Decimal
from typing import Callable, Iterable, Mapping

from forex_trader.domain.correlation_risk import CorrelationRiskGuard
from forex_trader.domain.enums import RiskDisposition
from forex_trader.domain.market_calendar import pair_holiday_blackout
from forex_trader.domain.models import AccountSnapshot, Quote, RiskAuthorization, TradeCandidate, jsonable
from forex_trader.domain.portfolio import OpenPosition
from forex_trader.domain.risk import RiskPolicy
from forex_trader.domain.sessions import SessionPhase, classify_phase

RiskStateProvider = Callable[[str, Decimal], Mapping[str, object]]


class EnhancedRiskPolicy(RiskPolicy):
    """Extend the existing independent veto with portfolio-state and contract hardening."""

    def __init__(
        self,
        *,
        risk_fraction: Decimal = Decimal("0.0015"),
        max_daily_loss_fraction: Decimal = Decimal("0.01"),
        max_open_positions: int = 3,
        max_units: int = 100_000,
        minimum_units: int = 1,
        scale_risk_by_score: bool = False,
        max_gross_exposure_fraction: Decimal = Decimal("4"),
        max_currency_exposure_fraction: Decimal = Decimal("2"),
        margin_buffer_fraction: Decimal = Decimal("0.20"),
        authorization_ttl_seconds: int = 15,
        correlation_guard: CorrelationRiskGuard | None = None,
        state_provider: RiskStateProvider | None = None,
        max_drawdown_fraction: Decimal = Decimal("0.10"),
        max_loss_streak: int = 6,
        max_reserved_risk_fraction: Decimal = Decimal("0.02"),
        gap_stress_multiplier: Decimal = Decimal("1.25"),
        environment: str = "practice",
        risk_policy_version: str = "practice-risk-v0.7",
    ) -> None:
        super().__init__(
            risk_fraction=risk_fraction,
            max_daily_loss_fraction=max_daily_loss_fraction,
            max_open_positions=max_open_positions,
            max_units=max_units,
            minimum_units=minimum_units,
            scale_risk_by_score=scale_risk_by_score,
            max_gross_exposure_fraction=max_gross_exposure_fraction,
            max_currency_exposure_fraction=max_currency_exposure_fraction,
            margin_buffer_fraction=margin_buffer_fraction,
            authorization_ttl_seconds=authorization_ttl_seconds,
            correlation_guard=correlation_guard,
        )
        if not Decimal("0") < max_drawdown_fraction <= Decimal("0.50"):
            raise ValueError("max_drawdown_fraction must be in (0, 0.50]")
        if max_loss_streak < 1:
            raise ValueError("max_loss_streak must be positive")
        if not Decimal("0") < max_reserved_risk_fraction <= Decimal("0.20"):
            raise ValueError("max_reserved_risk_fraction must be in (0, 0.20]")
        if gap_stress_multiplier < Decimal("1"):
            raise ValueError("gap_stress_multiplier must be at least 1")
        self.state_provider = state_provider
        self.max_drawdown_fraction = max_drawdown_fraction
        self.max_loss_streak = max_loss_streak
        self.max_reserved_risk_fraction = max_reserved_risk_fraction
        self.gap_stress_multiplier = gap_stress_multiplier
        self.environment = environment
        self.risk_policy_version = risk_policy_version

    def authorize(
        self,
        candidate: TradeCandidate,
        account: AccountSnapshot,
        quote: Quote,
        *,
        positions: Iterable[OpenPosition] = (),
        conversion_rate: Callable[[str, str], Decimal | None] | None = None,
        mark_price: Callable[[str], Decimal | None] | None = None,
        margin_rate: Decimal | None = None,
        maximum_position_units: Decimal | None = None,
    ) -> RiskAuthorization:
        capital_base = min(account.balance, account.nav)
        if classify_phase(quote.time) is SessionPhase.ROLLOVER:
            return self.deny(candidate, "rollover exposure is prohibited", account_id=account.account_id)
        holiday_blocked, holiday_reasons = pair_holiday_blackout(candidate.instrument, quote.time)
        if holiday_blocked:
            return self.deny(candidate, f"currency holiday blackout: {'; '.join(holiday_reasons)}", account_id=account.account_id)

        state: Mapping[str, object] = {}
        if self.state_provider is not None and capital_base > 0:
            state = self.state_provider(account.account_id, account.nav)
            drawdown = Decimal(str(state.get("drawdown_fraction", "0")))
            loss_streak = int(state.get("loss_streak", 0))
            reserved = Decimal(str(state.get("reserved_risk", "0")))
            pending = Decimal(str(state.get("pending_risk", "0")))
            if drawdown >= self.max_drawdown_fraction:
                return self.deny(candidate, f"trailing drawdown limit reached: {drawdown}", account_id=account.account_id)
            if loss_streak >= self.max_loss_streak:
                return self.deny(candidate, f"loss-streak observation limit reached: {loss_streak}", account_id=account.account_id)
            if reserved + pending >= capital_base * self.max_reserved_risk_fraction:
                return self.deny(candidate, "reserved/pending portfolio risk limit reached", account_id=account.account_id)

        result = super().authorize(
            candidate,
            account,
            quote,
            positions=positions,
            conversion_rate=conversion_rate,
            mark_price=mark_price,
            margin_rate=margin_rate,
            maximum_position_units=maximum_position_units,
        )
        if result.disposition is not RiskDisposition.GRANTED:
            return result

        reserved = Decimal(str(state.get("reserved_risk", "0"))) if state else Decimal("0")
        pending = Decimal(str(state.get("pending_risk", "0"))) if state else Decimal("0")
        stressed_loss = result.risk_amount * self.gap_stress_multiplier
        if capital_base > 0 and reserved + pending + stressed_loss > capital_base * self.max_reserved_risk_fraction:
            return self.deny(candidate, "new authorization would exceed reserved/pending stressed-risk cap", account_id=account.account_id)

        candidate_payload = json.dumps(jsonable(candidate), sort_keys=True, separators=(",", ":"))
        candidate_hash = hashlib.sha256(candidate_payload.encode()).hexdigest()
        entry_buffer = quote.spread
        entry_min = candidate.entry_price - entry_buffer if candidate.entry_price is not None else None
        entry_max = candidate.entry_price + entry_buffer if candidate.entry_price is not None else None
        limits = {
            "per_trade_risk_fraction": str(self.risk_fraction),
            "daily_loss_fraction": str(self.max_daily_loss_fraction),
            "reserved_risk_fraction": str(self.max_reserved_risk_fraction),
            "gap_stress_multiplier": str(self.gap_stress_multiplier),
            "drawdown_fraction": str(state.get("drawdown_fraction", "0")) if state else "0",
            "loss_streak": str(state.get("loss_streak", 0)) if state else "0",
        }
        integrity_source = "|".join(
            (
                str(result.authorization_id),
                candidate_hash,
                account.account_id,
                candidate.direction.value,
                str(result.units),
                str(stressed_loss),
                result.expires_at.isoformat() if result.expires_at is not None else "",
                self.risk_policy_version,
            )
        )
        integrity = hashlib.sha256(integrity_source.encode()).hexdigest()
        return replace(
            result,
            candidate_hash=candidate_hash,
            environment=self.environment,
            approved_direction=candidate.direction.value,
            maximum_units=result.units,
            entry_price_min=entry_min,
            entry_price_max=entry_max,
            stop_loss=candidate.stop_loss,
            maximum_loss=stressed_loss,
            required_protection=True,
            portfolio_snapshot_id=f"acct-{account.account_id}-{quote.time.isoformat()}",
            risk_policy_version=self.risk_policy_version,
            limits_consumed=limits,
            integrity_digest=integrity,
            reasons=(*result.reasons, f"gap-stressed maximum loss={stressed_loss}"),
        )
