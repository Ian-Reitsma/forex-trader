from __future__ import annotations

from decimal import ROUND_FLOOR, Decimal
from typing import Callable, Iterable
from uuid import uuid4

from forex_trader.domain.enums import DecisionDisposition, Direction, RiskDisposition
from forex_trader.domain.models import AccountSnapshot, Quote, RiskAuthorization, TradeCandidate, authorization_expiry
from forex_trader.domain.portfolio import OpenPosition, currency_exposure


class RiskPolicy:
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
    ) -> None:
        if not Decimal("0") < risk_fraction <= Decimal("0.02"):
            raise ValueError("risk_fraction must be greater than 0 and no more than 0.02")
        if not Decimal("0") < max_daily_loss_fraction <= Decimal("0.20"):
            raise ValueError("max_daily_loss_fraction must be greater than 0 and no more than 0.20")
        if max_open_positions < 1 or max_units < 1 or minimum_units < 1:
            raise ValueError("position and unit limits must be positive")
        if max_gross_exposure_fraction <= 0 or max_currency_exposure_fraction <= 0:
            raise ValueError("exposure limits must be positive")
        if not Decimal("0") <= margin_buffer_fraction < Decimal("1"):
            raise ValueError("margin_buffer_fraction must be between 0 and 1")
        if authorization_ttl_seconds < 1:
            raise ValueError("authorization_ttl_seconds must be positive")
        self.risk_fraction = risk_fraction
        self.max_daily_loss_fraction = max_daily_loss_fraction
        self.max_open_positions = max_open_positions
        self.max_units = max_units
        self.minimum_units = minimum_units
        self.scale_risk_by_score = scale_risk_by_score
        self.max_gross_exposure_fraction = max_gross_exposure_fraction
        self.max_currency_exposure_fraction = max_currency_exposure_fraction
        self.margin_buffer_fraction = margin_buffer_fraction
        self.authorization_ttl_seconds = authorization_ttl_seconds

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
        reasons: list[str] = []
        if candidate.disposition is not DecisionDisposition.TRADE:
            return self.deny(candidate, "candidate is not tradeable", account_id=account.account_id)
        if candidate.expired:
            return self.deny(candidate, "candidate expired before risk authorization", account_id=account.account_id)
        if candidate.entry_price is None or candidate.stop_loss is None or candidate.take_profit is None:
            return self.deny(candidate, "candidate lacks entry, stop, or target", account_id=account.account_id)
        if quote.instrument.upper() != candidate.instrument.upper():
            return self.deny(candidate, "risk quote instrument does not match candidate", account_id=account.account_id)
        if account.open_position_count >= self.max_open_positions:
            return self.deny(candidate, "maximum open-position count reached", account_id=account.account_id)

        capital_base = min(account.balance, account.nav)
        if capital_base <= 0:
            return self.deny(candidate, "account capital is not positive", account_id=account.account_id)
        marked_daily_loss = max(Decimal("0"), -(account.realized_pl_today + account.unrealized_pl))
        if marked_daily_loss >= capital_base * self.max_daily_loss_fraction:
            return self.deny(candidate, "daily marked-loss limit reached", account_id=account.account_id)

        if candidate.direction is Direction.LONG:
            if not candidate.stop_loss < candidate.entry_price < candidate.take_profit:
                return self.deny(candidate, "long protection levels are on the wrong side of entry", account_id=account.account_id)
        elif candidate.direction is Direction.SHORT:
            if not candidate.take_profit < candidate.entry_price < candidate.stop_loss:
                return self.deny(candidate, "short protection levels are on the wrong side of entry", account_id=account.account_id)
        else:
            return self.deny(candidate, "flat direction cannot be authorized", account_id=account.account_id)

        confidence_multiplier = Decimal("1")
        if self.scale_risk_by_score:
            confidence_multiplier = max(Decimal("0.50"), min(Decimal("1"), candidate.score))
        risk_budget = capital_base * self.risk_fraction * confidence_multiplier
        stop_distance = abs(candidate.entry_price - candidate.stop_loss)
        if stop_distance <= 0:
            return self.deny(candidate, "stop distance is invalid", account_id=account.account_id)

        per_unit_loss = self._per_unit_loss_account_currency(
            candidate.instrument,
            candidate.entry_price,
            stop_distance,
            account.currency,
            conversion_rate=conversion_rate,
        )
        if per_unit_loss is None or per_unit_loss <= 0:
            return self.deny(candidate, "instrument/account currency conversion is unsupported", account_id=account.account_id)
        raw_units = (risk_budget / per_unit_loss).to_integral_value(rounding=ROUND_FLOOR)
        units = min(self.max_units, int(raw_units))
        if maximum_position_units is not None and maximum_position_units > 0:
            units = min(units, int(maximum_position_units))
        if units < self.minimum_units:
            return self.deny(candidate, "calculated size is below broker minimum", account_id=account.account_id)

        existing = list(positions)
        if conversion_rate is not None:
            signed = Decimal(units if candidate.direction is Direction.LONG else -units)
            hypothetical = [
                *existing,
                OpenPosition(
                    instrument=candidate.instrument,
                    long_units=signed if signed > 0 else Decimal("0"),
                    short_units=signed if signed < 0 else Decimal("0"),
                    long_average_price=candidate.entry_price if signed > 0 else None,
                    short_average_price=candidate.entry_price if signed < 0 else None,
                ),
            ]

            def local_mark(instrument: str) -> Decimal | None:
                if instrument.upper() == candidate.instrument.upper():
                    return candidate.entry_price
                if mark_price is not None:
                    value = mark_price(instrument)
                    if value is not None:
                        return value
                for position in existing:
                    if position.instrument.upper() == instrument.upper():
                        return position.long_average_price or position.short_average_price
                return None

            exposure = currency_exposure(
                hypothetical,
                conversion_rate=conversion_rate,
                account_currency=account.currency,
                mark_price=local_mark,
            )
            if exposure.unpriced_instruments or exposure.unpriced_currencies:
                detail = ", ".join((*exposure.unpriced_instruments, *exposure.unpriced_currencies))
                return self.deny(candidate, f"portfolio exposure cannot be priced safely: {detail}", account_id=account.account_id)
            if exposure.gross_account_value > capital_base * self.max_gross_exposure_fraction:
                return self.deny(candidate, "gross portfolio currency exposure limit would be exceeded", account_id=account.account_id)
            if any(amount > capital_base * self.max_currency_exposure_fraction for amount in exposure.by_currency.values()):
                return self.deny(candidate, "single-currency gross exposure limit would be exceeded", account_id=account.account_id)
            reasons.append(f"gross currency exposure={exposure.gross_account_value}")

            if margin_rate is not None and margin_rate > 0 and account.margin_available > 0:
                _, quote_currency = candidate.instrument.split("_", maxsplit=1)
                quote_notional = Decimal(units) * candidate.entry_price
                conversion = Decimal("1") if quote_currency == account.currency.upper() else conversion_rate(quote_currency, account.currency.upper())
                if conversion is None or conversion <= 0:
                    return self.deny(candidate, "margin notional cannot be converted safely", account_id=account.account_id)
                estimated_margin = quote_notional * conversion * margin_rate
                usable_margin = account.margin_available * (Decimal("1") - self.margin_buffer_fraction)
                if estimated_margin > usable_margin:
                    return self.deny(candidate, "estimated margin would violate the margin reserve", account_id=account.account_id)
                reasons.append(f"estimated margin={estimated_margin}")

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
            account_id=account.account_id,
            expires_at=authorization_expiry(self.authorization_ttl_seconds),
        )

    @staticmethod
    def _per_unit_loss_account_currency(
        instrument: str,
        entry: Decimal,
        stop_distance: Decimal,
        account_currency: str,
        *,
        conversion_rate: Callable[[str, str], Decimal | None] | None = None,
    ) -> Decimal | None:
        base, quote = instrument.split("_", maxsplit=1)
        if quote == account_currency.upper():
            return stop_distance
        if conversion_rate is not None:
            rate = conversion_rate(quote, account_currency.upper())
            if rate is not None and rate > 0:
                return stop_distance * rate
        if account_currency.upper() == "USD" and base == "USD":
            return stop_distance / entry
        return None

    @staticmethod
    def deny(candidate: TradeCandidate, reason: str, *, account_id: str | None = None) -> RiskAuthorization:
        return RiskAuthorization(
            authorization_id=uuid4(),
            candidate_id=candidate.candidate_id,
            disposition=RiskDisposition.DENIED,
            units=0,
            risk_amount=Decimal("0"),
            reasons=(reason,),
            account_id=account_id,
        )
