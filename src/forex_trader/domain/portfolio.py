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


@dataclass(frozen=True, slots=True)
class ExposureReport:
    gross_account_value: Decimal
    by_currency: dict[str, Decimal]
    unpriced_currencies: tuple[str, ...] = ()
    unpriced_instruments: tuple[str, ...] = ()


def currency_exposure(
    positions: Iterable[OpenPosition],
    *,
    conversion_rate: Callable[[str, str], Decimal | None],
    account_currency: str,
    mark_price: Callable[[str], Decimal | None],
) -> ExposureReport:
    """Compute absolute currency-leg exposure in account-currency terms.

    A long 100k EUR_USD position contributes +100k EUR and -USD notional. A
    short position contributes the inverse. The result intentionally measures
    concentration rather than P/L direction.
    """
    legs: dict[str, Decimal] = {}
    unpriced_instruments: set[str] = set()
    for position in positions:
        net_units = position.net_units
        if net_units == 0:
            continue
        base, quote = position.instrument.upper().split("_", maxsplit=1)
        price = mark_price(position.instrument)
        if price is None or price <= 0:
            unpriced_instruments.add(position.instrument.upper())
            continue
        legs[base] = legs.get(base, Decimal("0")) + net_units
        legs[quote] = legs.get(quote, Decimal("0")) - net_units * price

    converted: dict[str, Decimal] = {}
    unpriced_currencies: set[str] = set()
    for currency, amount in legs.items():
        rate = conversion_rate(currency, account_currency.upper())
        if rate is None or rate <= 0:
            unpriced_currencies.add(currency)
            continue
        converted[currency] = abs(amount * rate)
    return ExposureReport(
        gross_account_value=sum(converted.values(), Decimal("0")),
        by_currency=converted,
        unpriced_currencies=tuple(sorted(unpriced_currencies)),
        unpriced_instruments=tuple(sorted(unpriced_instruments)),
    )
