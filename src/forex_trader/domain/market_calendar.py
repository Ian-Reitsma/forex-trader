from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from zoneinfo import ZoneInfo

import holidays


@dataclass(frozen=True, slots=True)
class CurrencyHoliday:
    currency: str
    local_date: str
    calendar_code: str
    holiday_name: str


# Currency -> (holiday calendar code, local market timezone, is_financial_calendar).
# EUR uses TARGET/ECB settlement closures rather than a single member-state calendar.
_CURRENCY_CALENDARS: dict[str, tuple[str, str, bool]] = {
    "EUR": ("XECB", "Europe/Berlin", True),
    "USD": ("US", "America/New_York", False),
    "GBP": ("GB", "Europe/London", False),
    "JPY": ("JP", "Asia/Tokyo", False),
    "CHF": ("CH", "Europe/Zurich", False),
    "CAD": ("CA", "America/Toronto", False),
    "AUD": ("AU", "Australia/Sydney", False),
    "NZD": ("NZ", "Pacific/Auckland", False),
    "SEK": ("SE", "Europe/Stockholm", False),
    "NOK": ("NO", "Europe/Oslo", False),
    "DKK": ("DK", "Europe/Copenhagen", False),
    "PLN": ("PL", "Europe/Warsaw", False),
    "CZK": ("CZ", "Europe/Prague", False),
    "HUF": ("HU", "Europe/Budapest", False),
    "SGD": ("SG", "Asia/Singapore", False),
    "HKD": ("HK", "Asia/Hong_Kong", False),
    "CNY": ("CN", "Asia/Shanghai", False),
    "CNH": ("CN", "Asia/Shanghai", False),
    "MXN": ("MX", "America/Mexico_City", False),
    "TRY": ("TR", "Europe/Istanbul", False),
    "ZAR": ("ZA", "Africa/Johannesburg", False),
    "INR": ("IN", "Asia/Kolkata", False),
    "THB": ("TH", "Asia/Bangkok", False),
}


def currency_holiday(currency: str, instant: datetime) -> CurrencyHoliday | None:
    """Return the mapped public/settlement holiday affecting *currency* at *instant*.

    The function is deliberately conservative. Spot FX may remain technically open while
    one currency's banking/settlement center is closed, but liquidity and price formation
    can degrade enough that an unproven scalp strategy should not open new risk.
    """
    if instant.tzinfo is None:
        raise ValueError("holiday checks require a timezone-aware timestamp")
    currency = currency.upper()
    config = _CURRENCY_CALENDARS.get(currency)
    if config is None:
        return None
    calendar_code, timezone_name, financial = config
    local_date = instant.astimezone(ZoneInfo(timezone_name)).date()
    calendar = (
        holidays.financial_holidays(calendar_code, years=[local_date.year])
        if financial
        else holidays.country_holidays(calendar_code, years=[local_date.year])
    )
    name = calendar.get(local_date)
    if name is None:
        return None
    return CurrencyHoliday(
        currency=currency,
        local_date=local_date.isoformat(),
        calendar_code=calendar_code,
        holiday_name=str(name),
    )


def pair_holiday_blackout(instrument: str, instant: datetime) -> tuple[bool, tuple[str, ...]]:
    """Return a conservative new-entry blackout for pair currency holidays."""
    try:
        base, quote = instrument.upper().split("_", maxsplit=1)
    except ValueError as exc:
        raise ValueError("instrument must use BASE_QUOTE format") from exc
    hits = [holiday for currency in (base, quote) if (holiday := currency_holiday(currency, instant))]
    if not hits:
        return False, ()
    reasons = tuple(
        f"{hit.currency} {hit.calendar_code} holiday on {hit.local_date}: {hit.holiday_name}"
        for hit in hits
    )
    return True, reasons
