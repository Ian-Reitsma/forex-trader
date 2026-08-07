from datetime import UTC, datetime, timedelta
from decimal import Decimal

from forex_trader.domain.enums import DecisionDisposition, Direction
from forex_trader.domain.models import FundamentalAssessment, Quote, TechnicalAssessment
from forex_trader.domain.strategy import SignalFusionPolicy


def technical(direction: Direction = Direction.LONG) -> TechnicalAssessment:
    return TechnicalAssessment(
        instrument="EUR_USD",
        direction=direction,
        score=Decimal("0.85"),
        atr=Decimal("0.001"),
        rsi=Decimal("55"),
        entry_reference=Decimal("1.1000"),
        stop_reference=Decimal("1.0980") if direction is Direction.LONG else Decimal("1.1020"),
        take_profit_reference=Decimal("1.1040") if direction is Direction.LONG else Decimal("1.0960"),
        reasons=("technical setup",),
        liquidity_sweep=True,
        displacement=True,
        reward_risk=Decimal("2"),
    )


def fundamental(diff: str = "0.5", confidence: str = "0.9") -> FundamentalAssessment:
    return FundamentalAssessment(
        "EUR_USD",
        Decimal("0.3"),
        Decimal("-0.2"),
        Decimal(diff),
        Decimal(confidence),
        ("fundamental setup",),
    )


def quote(spread: str = "0.0001") -> Quote:
    half = Decimal(spread) / 2
    return Quote("EUR_USD", Decimal("1.1000") - half, Decimal("1.1000") + half, datetime.now(UTC))


def test_fusion_trades_aligned_setup() -> None:
    result = SignalFusionPolicy(minimum_score=Decimal("0.5")).evaluate(
        technical(), fundamental(), quote()
    )
    assert result.disposition is DecisionDisposition.TRADE
    assert result.direction is Direction.LONG


def test_fusion_abstains_on_conflict() -> None:
    result = SignalFusionPolicy().evaluate(technical(), fundamental("-0.8"), quote())
    assert result.disposition is DecisionDisposition.ABSTAIN
    assert "conflicts" in result.reasons[-1]


def test_fusion_abstains_on_wide_spread() -> None:
    result = SignalFusionPolicy().evaluate(technical(), fundamental(), quote("0.0005"))
    assert result.disposition is DecisionDisposition.ABSTAIN
    assert "spread" in result.reasons[-1]


def test_fusion_requires_confirmation_and_fresh_quote() -> None:
    missing_sweep = TechnicalAssessment(
        **{
            "instrument": "EUR_USD",
            "direction": Direction.LONG,
            "score": Decimal("0.9"),
            "atr": Decimal("0.001"),
            "rsi": Decimal("55"),
            "entry_reference": Decimal("1.1000"),
            "stop_reference": Decimal("1.0980"),
            "take_profit_reference": Decimal("1.1040"),
            "reasons": (),
            "liquidity_sweep": False,
            "displacement": True,
        }
    )
    result = SignalFusionPolicy(minimum_score=Decimal("0.5")).evaluate(
        missing_sweep, fundamental(), quote()
    )
    assert result.disposition is DecisionDisposition.ABSTAIN
    assert "sweep" in result.reasons[-1]

    stale_quote = Quote(
        "EUR_USD",
        Decimal("1.09995"),
        Decimal("1.10005"),
        technical().signal_time + timedelta(hours=1),
    )
    result = SignalFusionPolicy(minimum_score=Decimal("0.5")).evaluate(
        technical(), fundamental(), stale_quote
    )
    assert "gap" in result.reasons[-1]


def test_fusion_rejects_low_executable_reward_risk() -> None:
    setup = technical()
    setup = TechnicalAssessment(
        instrument=setup.instrument,
        direction=setup.direction,
        score=setup.score,
        atr=setup.atr,
        rsi=setup.rsi,
        entry_reference=setup.entry_reference,
        stop_reference=Decimal("1.0990"),
        take_profit_reference=Decimal("1.1010"),
        reasons=setup.reasons,
        signal_time=setup.signal_time,
        liquidity_sweep=True,
        displacement=True,
    )
    result = SignalFusionPolicy(minimum_score=Decimal("0.5")).evaluate(
        setup, fundamental(), quote()
    )
    assert result.disposition is DecisionDisposition.ABSTAIN
    assert "reward/risk" in result.reasons[-1]
