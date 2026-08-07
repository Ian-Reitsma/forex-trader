from __future__ import annotations

from decimal import Decimal, ROUND_FLOOR
from uuid import uuid4

from forex_trader.domain.enums import DecisionDisposition, RiskDisposition
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
    ) -> None:
        self.risk_fraction = risk_fraction
        self.max_daily_loss_fraction = max_daily_loss_fraction
        self.max_open_positions = max_open_positions
        self.max_units = max_units
        self.minimum_units = minimum_units

    def authorize(
        self,
        candidate: TradeCandidate,
        account: AccountSnapshot,
        quote: Quote,
    ) -> RiskAuthorization:
        reasons: list[str] = []
        if candidate.disposition is not DecisionDisposition.TRADE:
            return self._deny(candidate, "candidate is not tradeable")
        if candidate.entry_price is None or candidate.stop_loss is None:
            return self._deny(candidate, "candidate lacks entry or stop")
        if account.open_position_count >= self.max_open_positions:
            return self._deny(candidate, "maximum open-position count reached")
        if account.balance <= 0:
            return self._deny(candidate, "account balance is not positive")
        daily_loss = max(Decimal("0"), -account.realized_pl_today)
        if daily_loss >= account.balance * self.max_daily_loss_fraction:
            return self._deny(candidate, "daily loss limit reached")

        risk_amount = account.balance * self.risk_fraction
        stop_distance = abs(candidate.entry_price - candidate.stop_loss)
        if stop_distance <= 0:
            return self._deny(candidate, "stop distance is invalid")

        per_unit_loss = self._per_unit_loss_usd(
            candidate.instrument,
            candidate.entry_price,
            stop_distance,
            account.currency,
        )
        if per_unit_loss is None or per_unit_loss <= 0:
            return self._deny(candidate, "instrument/account currency conversion is unsupported")
        raw_units = (risk_amount / per_unit_loss).to_integral_value(rounding=ROUND_FLOOR)
        units = min(self.max_units, int(raw_units))
        if units < self.minimum_units:
            return self._deny(candidate, "calculated size is below broker minimum")
        reasons.extend(
            (
                f"risk budget={risk_amount}",
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
    def _deny(candidate: TradeCandidate, reason: str) -> RiskAuthorization:
        return RiskAuthorization(
            authorization_id=uuid4(),
            candidate_id=candidate.candidate_id,
            disposition=RiskDisposition.DENIED,
            units=0,
            risk_amount=Decimal("0"),
            reasons=(reason,),
        )
