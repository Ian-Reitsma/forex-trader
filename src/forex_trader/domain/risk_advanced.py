from __future__ import annotations

import hashlib
import json
from dataclasses import replace
from decimal import Decimal
from typing import Callable, Iterable, Mapping

from forex_trader.domain.correlation_risk import CorrelationRiskGuard
from forex_trader.domain.enums import RiskDisposition
from forex_trader.domain.macro_factor_risk import MacroFactorClusterGuard
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
        macro_factor_guard: MacroFactorClusterGuard | None = None,
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
        self.macro_factor_guard = macro_factor_guard
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
        existing = list(positions)
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
            positions=existing,
            conversion_rate=conversion_rate,
            mark_price=mark_price,
            margin_rate=margin_rate,
            maximum_position_units=maximum_position_units,
        )
        if result.disposition is not RiskDisposition.GRANTED:
            return result

        factor_reason: str | None = None
        factor_name: str | None = None
        factor_exposure = Decimal("0")
        if self.macro_factor_guard is not None:
            if conversion_rate is None or mark_price is None:
                return self.deny(
                    candidate,
                    "macro factor risk requires conversion and mark-price providers",
                    account_id=account.account_id,
                )
            assert candidate.entry_price is not None
            factor_decision = self.macro_factor_guard.evaluate_candidate(
                candidate_instrument=candidate.instrument,
                candidate_direction=candidate.direction,
                candidate_units=result.units,
                candidate_entry_price=candidate.entry_price,
                positions=existing,
                account_currency=account.currency,
                capital_base=capital_base,
                conversion_rate=conversion_rate,
                mark_price=mark_price,
            )
            if factor_decision.blocked:
                return self.deny(
                    candidate,
                    factor_decision.reason or "macro factor concentration vetoed the position",
                    account_id=account.account_id,
                )
            factor_name = factor_decision.maximum_factor
            factor_exposure = factor_decision.maximum_factor_exposure
            if factor_name is not None:
                factor_reason = f"maximum macro factor exposure={factor_name}:{factor_exposure}"

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
        if self.macro_factor_guard is not None:
            limits["macro_factor_exposure_fraction"] = str(
                self.macro_factor_guard.maximum_factor_exposure_fraction
            )
            if factor_name is not None:
                limits["maximum_macro_factor"] = factor_name
                limits["maximum_macro_factor_exposure"] = str(factor_exposure)
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
        extra_reasons = (factor_reason,) if factor_reason is not None else ()
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
            reasons=(*result.reasons, *extra_reasons, f"gap-stressed maximum loss={stressed_loss}"),
        )
