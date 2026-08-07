from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import uuid4

from forex_trader.domain.correlation_risk import CorrelationRiskGuard
from forex_trader.domain.enums import DecisionDisposition, Direction, RiskDisposition
from forex_trader.domain.models import AccountSnapshot, Candle, Quote, TradeCandidate
from forex_trader.domain.portfolio import OpenPosition
from forex_trader.domain.risk import RiskPolicy


def series(scale: Decimal = Decimal("1"), *, inverse: bool = False) -> list[Candle]:
    start = datetime(2026, 8, 1, tzinfo=UTC)
    values = [
        Decimal("1") + Decimal(index) * Decimal("0.001") + Decimal((index % 5) - 2) * Decimal("0.0002")
        for index in range(81)
    ]
    if inverse:
        values = [Decimal("3") - value for value in values]
    values = [value * scale for value in values]
    return [
        Candle(
            start + timedelta(hours=index),
            value,
            value + Decimal("0.0003"),
            value - Decimal("0.0003"),
            value,
        )
        for index, value in enumerate(values)
    ]


def candidate(direction: Direction = Direction.LONG) -> TradeCandidate:
    return TradeCandidate(
        candidate_id=uuid4(),
        instrument="EUR_USD",
        direction=direction,
        disposition=DecisionDisposition.TRADE,
        score=Decimal("0.8"),
        entry_price=Decimal("1.1000"),
        stop_loss=Decimal("1.0980") if direction is Direction.LONG else Decimal("1.1020"),
        take_profit=Decimal("1.1040") if direction is Direction.LONG else Decimal("1.0960"),
        technical_score=Decimal("0.8"),
        fundamental_score=Decimal("0.5"),
        reasons=(),
    )


def loader(instrument: str, granularity: str, count: int) -> list[Candle]:
    assert granularity == "H1"
    data = {
        "EUR_USD": series(),
        "GBP_USD": series(Decimal("1.8")),
        "USD_JPY": series(Decimal("120"), inverse=True),
    }[instrument]
    return data[-count:]


def test_signed_correlation_blocks_same_direction_duplicate_risk() -> None:
    guard = CorrelationRiskGuard(loader, maximum_signed_correlation=0.85)
    decision = guard.evaluate(
        candidate(Direction.LONG),
        [OpenPosition("GBP_USD", long_units=Decimal("1000"))],
    )
    assert decision.blocked is True
    assert decision.max_signed_correlation is not None
    assert decision.max_signed_correlation > 0.99
    assert "GBP_USD" in str(decision.reason)


def test_signed_correlation_allows_hedging_direction_and_handles_negative_raw_corr() -> None:
    guard = CorrelationRiskGuard(loader, maximum_signed_correlation=0.85)
    hedge = guard.evaluate(
        candidate(Direction.SHORT),
        [OpenPosition("GBP_USD", long_units=Decimal("1000"))],
    )
    assert hedge.blocked is False
    assert hedge.max_signed_correlation is not None
    assert hedge.max_signed_correlation < 0

    # EUR/USD and USD/JPY series are negatively related. Long EUR/USD plus short
    # USD/JPY transforms that raw negative correlation into strongly correlated P/L.
    duplicate_pnl = guard.evaluate(
        candidate(Direction.LONG),
        [OpenPosition("USD_JPY", short_units=Decimal("-1000"))],
    )
    assert duplicate_pnl.blocked is True


def test_correlation_guard_fails_closed_when_existing_position_history_is_unavailable() -> None:
    guard = CorrelationRiskGuard(
        lambda instrument, granularity, count: [] if instrument == "GBP_USD" else series(),
        fail_closed=True,
    )
    decision = guard.evaluate(
        candidate(),
        [OpenPosition("GBP_USD", long_units=Decimal("100"))],
    )
    assert decision.blocked is True
    assert "could not price" in str(decision.reason)


def test_risk_policy_applies_correlation_veto_before_position_sizing() -> None:
    guard = CorrelationRiskGuard(loader, maximum_signed_correlation=0.85)
    policy = RiskPolicy(correlation_guard=guard, max_open_positions=3)
    trade = candidate()
    quote = Quote(
        "EUR_USD",
        Decimal("1.0999"),
        Decimal("1.1000"),
        datetime(2026, 8, 7, tzinfo=UTC),
    )
    account = AccountSnapshot(
        "A",
        "USD",
        Decimal("10000"),
        Decimal("10000"),
        open_position_count=1,
    )
    authorization = policy.authorize(
        trade,
        account,
        quote,
        positions=[OpenPosition("GBP_USD", long_units=Decimal("1000"))],
    )
    assert authorization.disposition is RiskDisposition.DENIED
    assert "correlation" in authorization.reasons[0]


def test_correlation_guard_validates_configuration() -> None:
    try:
        CorrelationRiskGuard(loader, lookback=20, minimum_observations=40)
    except ValueError as exc:
        assert "lookback" in str(exc)
    else:
        raise AssertionError("invalid lookback should fail")
