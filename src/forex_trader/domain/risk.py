from __future__ import annotations

from decimal import ROUND_FLOOR, Decimal
from uuid import uuid4

from forex_trader.domain.enums import DecisionDisposition, Direction, RiskDisposition
from forex_trader.domain.models import AccountSnapshot, Quote, RiskAuthorization, TradeCandidate


class RiskPolicy:
    def __init__(
        self,
        *,
        risk_fraction: Decimal = Decimal("0.0025"),
        max_daily_loss_fraction: Decimal = Decimal("0.02"),
        max_open_positions: int = 3,
        max_units: int = 100_000,
        minimum_units: int = 1,
        scale_risk_by_score: bool = True,
    ) -> None:
        if not Decimal("0") < risk_fraction <= Decimal("0.02"):
            raise ValueError("risk_fraction must be greater than 0 and no more than 0.02")
        if not Decimal("0") < max_daily_loss_fraction <= Decimal("0.20"):
            raise ValueError("max_daily_loss_fraction must be greater than 0 and no more than 0.20")
        if max_open_positions < 1 or max_units < 1 or minimum_units < 1:
            raise ValueError("position and unit limits must be positive")
        self.risk_fraction = risk_fraction
        self.max_daily_loss_fraction = max_daily_loss_fraction
        self.max_open_positions = max_open_positions
        self.max_units = max_units
        self.minimum_units = minimum_units
        self.scale_risk_by_score = scale_risk_by_score

    def authorize(
        self,
        candidate: TradeCandidate,
        account: AccountSnapshot,
        quote: Quote,
    ) -> RiskAuthorization:
        reasons: list[str] = []
        if candidate.disposition is not DecisionDisposition.TRADE:
            return self.deny(candidate, "candidate is not tradeable")
        if candidate.entry_price is None or candidate.stop_loss is None or candidate.take_profit is None:
            return self.deny(candidate, "candidate lacks entry, stop, or target")
        if account.open_position_count >= self.max_open_positions:
            return self.deny(candidate, "maximum open-position count reached")

        capital_base = min(account.balance, account.nav)
        if capital_base <= 0:
            return self.deny(candidate, "account capital is not positive")
        daily_loss = max(Decimal("0"), -account.realized_pl_today)
        if daily_loss >= capital_base * self.max_daily_loss_fraction:
            return self.deny(candidate, "daily loss limit reached")

        if candidate.direction is Direction.LONG:
            if not candidate.stop_loss < candidate.entry_price < candidate.take_profit:
                return self.deny(candidate, "long protection levels are on the wrong side of entry")
        elif candidate.direction is Direction.SHORT:
            if not candidate.take_profit < candidate.entry_price < candidate.stop_loss:
                return self.deny(candidate, "short protection levels are on the wrong side of entry")
        else:
            return self.deny(candidate, "flat direction cannot be authorized")

        confidence_multiplier = Decimal("1")
        if self.scale_risk_by_score:
            confidence_multiplier = max(
                Decimal("0.50"), min(Decimal("1"), candidate.score)
            )
        risk_budget = capital_base * self.risk_fraction * confidence_multiplier
        stop_distance = abs(candidate.entry_price - candidate.stop_loss)
        if stop_distance <= 0:
            return self.deny(candidate, "stop distance is invalid")

        per_unit_loss = self._per_unit_loss_usd(
            candidate.instrument,
            candidate.entry_price,
            stop_distance,
            account.currency,
        )
        if per_unit_loss is None or per_unit_loss <= 0:
            return self.deny(candidate, "instrument/account currency conversion is unsupported")
        raw_units = (risk_budget / per_unit_loss).to_integral_value(rounding=ROUND_FLOOR)
        units = min(self.max_units, int(raw_units))
        if units < self.minimum_units:
            return self.deny(candidate, "calculated size is below broker minimum")
        reasons.extend(
            (
                f"capital base={capital_base}",
                f"confidence multiplier={confidence_multiplier}",
                f"risk budget={risk_budget}",
                f"stop distance={stop_distance}",
                f"authorized units={units}",
            )
        )
        return RiskAuthorization(
            authorization_id=uuid4(),
            candidate_id=candidate.candidate_id,
            disposition=RiskDisposition.GRANTED,
            units=units,
            risk_amount=per_unit_loss * Decimal(units),
            reasons=tuple(reasons),
        )

    @staticmethod
    def _per_unit_loss_usd(
        instrument: str,
        entry: Decimal,
        stop_distance: Decimal,
        account_currency: str,
    ) -> Decimal | None:
        if account_currency.upper() != "USD":
            return None
        base, quote = instrument.split("_", maxsplit=1)
        if quote == "USD":
            return stop_distance
        if base == "USD":
            return stop_distance / entry
        return None

    @staticmethod
    def deny(candidate: TradeCandidate, reason: str) -> RiskAuthorization:
        return RiskAuthorization(
            authorization_id=uuid4(),
            candidate_id=candidate.candidate_id,
            disposition=RiskDisposition.DENIED,
            units=0,
            risk_amount=Decimal("0"),
            reasons=(reason,),
        )
