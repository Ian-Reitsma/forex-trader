from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Callable, Iterable


@dataclass(frozen=True, slots=True)
class OpenPosition:
    instrument: str
    long_units: Decimal = Decimal("0")
    short_units: Decimal = Decimal("0")
    long_average_price: Decimal | None = None
    short_average_price: Decimal | None = None
    unrealized_pl: Decimal = Decimal("0")

    @property
    def net_units(self) -> Decimal:
        return self.long_units + self.short_units

    @property
    def gross_units(self) -> Decimal:
        return abs(self.long_units) + abs(self.short_units)


@dataclass(frozen=True, slots=True)
class ExposureReport:
    gross_account_value: Decimal
    by_currency: dict[str, Decimal]
    gross_by_currency: dict[str, Decimal] | None = None
    net_by_currency: dict[str, Decimal] | None = None
    unpriced_currencies: tuple[str, ...] = ()
    unpriced_instruments: tuple[str, ...] = ()


def currency_exposure(
    positions: Iterable[OpenPosition],
    *,
    conversion_rate: Callable[[str, str], Decimal | None],
    account_currency: str,
    mark_price: Callable[[str], Decimal | None],
) -> ExposureReport:
    """Compute net and gross currency-leg exposure in account-currency terms.

    Gross legs are preserved even when a hedging account carries simultaneous long
    and short trades, so a net-zero position cannot disappear from margin/risk views.
    """
    net_legs: dict[str, Decimal] = {}
    gross_legs: dict[str, Decimal] = {}
    unpriced_instruments: set[str] = set()
    for position in positions:
        if position.gross_units == 0:
            continue
        base, quote = position.instrument.upper().split("_", maxsplit=1)
        price = mark_price(position.instrument)
        if price is None or price <= 0:
            unpriced_instruments.add(position.instrument.upper())
            continue

        long_units = max(Decimal("0"), position.long_units)
        short_units = abs(min(Decimal("0"), position.short_units))
        net_units = long_units - short_units
        net_legs[base] = net_legs.get(base, Decimal("0")) + net_units
        net_legs[quote] = net_legs.get(quote, Decimal("0")) - net_units * price
        gross_legs[base] = gross_legs.get(base, Decimal("0")) + long_units + short_units
        gross_legs[quote] = gross_legs.get(quote, Decimal("0")) + (long_units + short_units) * price

    converted_net: dict[str, Decimal] = {}
    converted_gross: dict[str, Decimal] = {}
    unpriced_currencies: set[str] = set()
    for currency in sorted(set(net_legs) | set(gross_legs)):
        rate = conversion_rate(currency, account_currency.upper())
        if rate is None or rate <= 0:
            unpriced_currencies.add(currency)
            continue
        converted_net[currency] = net_legs.get(currency, Decimal("0")) * rate
        converted_gross[currency] = gross_legs.get(currency, Decimal("0")) * rate

    # by_currency remains the concentration view expected by existing callers; it
    # is now gross rather than silently netting hedged legs to zero.
    return ExposureReport(
        gross_account_value=sum(converted_gross.values(), Decimal("0")),
        by_currency=converted_gross,
        gross_by_currency=converted_gross,
        net_by_currency=converted_net,
        unpriced_currencies=tuple(sorted(unpriced_currencies)),
        unpriced_instruments=tuple(sorted(unpriced_instruments)),
    )
