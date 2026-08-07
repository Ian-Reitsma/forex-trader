from datetime import UTC, datetime
from decimal import Decimal

import pytest

from forex_trader.domain.models import Candle, Quote, jsonable


def test_candle_rejects_invalid_ohlc() -> None:
    with pytest.raises(ValueError):
        Candle(
            datetime.now(UTC),
            Decimal("1.2"),
            Decimal("1.1"),
            Decimal("1.0"),
            Decimal("1.2"),
        )


def test_quote_mid_and_spread() -> None:
    quote = Quote("EUR_USD", Decimal("1.1000"), Decimal("1.1002"), datetime.now(UTC))
    assert quote.mid == Decimal("1.1001")
    assert quote.spread == Decimal("0.0002")
    assert jsonable(quote)["bid"] == "1.1000"
