from decimal import Decimal

from forex_trader.adapters.synthetic import SyntheticMarketData
from forex_trader.domain.enums import Direction
from forex_trader.domain.technicals import assess_technicals, atr, ema, pip_size, rsi


def test_indicators() -> None:
    values = [Decimal(index) for index in range(1, 31)]
    assert ema(values, 5) > Decimal("25")
    assert rsi(values, 14) == Decimal("100")


def test_atr_and_long_assessment() -> None:
    market = SyntheticMarketData(seed=4, direction="long")
    lower = market.candles("EUR_USD", "M5", 200)
    higher = market.candles("EUR_USD", "H1", 200)
    assert atr(lower) > 0
    assessment = assess_technicals("EUR_USD", lower, higher)
    assert assessment.direction is Direction.LONG
    assert assessment.score >= Decimal("0.60")
    assert assessment.stop_reference is not None
    assert assessment.take_profit_reference is not None


def test_short_assessment() -> None:
    market = SyntheticMarketData(seed=4, direction="short")
    assessment = assess_technicals(
        "USD_JPY",
        market.candles("USD_JPY", "M5", 200),
        market.candles("USD_JPY", "H1", 200),
    )
    assert assessment.direction is Direction.SHORT
    assert pip_size("USD_JPY") == Decimal("0.01")
