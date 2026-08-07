from datetime import UTC, datetime
from decimal import Decimal
from uuid import uuid4

import pytest

from forex_trader.domain.enums import DecisionDisposition, Direction, RiskDisposition
from forex_trader.domain.models import AccountSnapshot, Quote, TradeCandidate
from forex_trader.domain.risk import RiskPolicy


def candidate(instrument: str = "EUR_USD") -> TradeCandidate:
    return TradeCandidate(
        candidate_id=uuid4(),
        instrument=instrument,
        direction=Direction.LONG,
        disposition=DecisionDisposition.TRADE,
        score=Decimal("0.8"),
        entry_price=Decimal("1.1000"),
        stop_loss=Decimal("1.0980"),
        take_profit=Decimal("1.1040"),
        technical_score=Decimal("0.8"),
        fundamental_score=Decimal("0.7"),
        reasons=(),
    )


def account(**changes: object) -> AccountSnapshot:
    data = dict(
        account_id="A",
        currency="USD",
        balance=Decimal("10000"),
        nav=Decimal("10000"),
    )
    data.update(changes)
    return AccountSnapshot(**data)


def test_risk_sizes_quote_usd_pair() -> None:
    quote = Quote("EUR_USD", Decimal("1.1"), Decimal("1.1001"), datetime.now(UTC))
    auth = RiskPolicy(risk_fraction=Decimal("0.01")).authorize(candidate(), account(), quote)
    assert auth.disposition is RiskDisposition.GRANTED
    assert auth.units == 40_000
    assert auth.risk_amount == Decimal("80.0000")


def test_risk_denies_cross_without_conversion() -> None:
    quote = Quote("EUR_GBP", Decimal("0.85"), Decimal("0.8501"), datetime.now(UTC))
    auth = RiskPolicy().authorize(candidate("EUR_GBP"), account(), quote)
    assert auth.disposition is RiskDisposition.DENIED


def test_risk_denies_daily_loss_limit() -> None:
    quote = Quote("EUR_USD", Decimal("1.1"), Decimal("1.1001"), datetime.now(UTC))
    auth = RiskPolicy().authorize(
        candidate(), account(realized_pl_today=Decimal("-250")), quote
    )
    assert auth.disposition is RiskDisposition.DENIED


def test_risk_validates_policy_and_protection_levels() -> None:
    with pytest.raises(ValueError):
        RiskPolicy(risk_fraction=Decimal("0"))
    with pytest.raises(ValueError):
        RiskPolicy(max_open_positions=0)

    original = candidate()
    invalid = TradeCandidate(
        candidate_id=original.candidate_id,
        instrument=original.instrument,
        direction=original.direction,
        disposition=original.disposition,
        score=original.score,
        entry_price=original.entry_price,
        stop_loss=Decimal("1.1010"),
        take_profit=original.take_profit,
        technical_score=original.technical_score,
        fundamental_score=original.fundamental_score,
        reasons=original.reasons,
    )
    quote = Quote("EUR_USD", Decimal("1.1"), Decimal("1.1001"), datetime.now(UTC))
    auth = RiskPolicy().authorize(invalid, account(), quote)
    assert auth.disposition is RiskDisposition.DENIED
    assert "wrong side" in auth.reasons[0]


def test_risk_denies_position_limit_and_nonpositive_capital() -> None:
    quote = Quote("EUR_USD", Decimal("1.1"), Decimal("1.1001"), datetime.now(UTC))
    policy = RiskPolicy(max_open_positions=1)
    position_limit = policy.authorize(candidate(), account(open_position_count=1), quote)
    no_capital = policy.authorize(candidate(), account(nav=Decimal("0")), quote)
    assert position_limit.disposition is RiskDisposition.DENIED
    assert no_capital.disposition is RiskDisposition.DENIED
