from datetime import UTC, datetime
from decimal import Decimal
from uuid import uuid4

import pytest

from forex_trader.domain.enums import DecisionDisposition, Direction, RiskDisposition
from forex_trader.domain.models import AccountSnapshot, Quote, TradeCandidate
from forex_trader.domain.risk import RiskPolicy


def candidate(instrument: str = "EUR_USD", *, score: str = "0.8") -> TradeCandidate:
    return TradeCandidate(
        candidate_id=uuid4(),
        instrument=instrument,
        direction=Direction.LONG,
        disposition=DecisionDisposition.TRADE,
        score=Decimal(score),
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


def test_risk_sizes_quote_usd_pair_from_stop_budget_not_uncalibrated_score() -> None:
    quote = Quote("EUR_USD", Decimal("1.1"), Decimal("1.1001"), datetime.now(UTC))
    policy = RiskPolicy(risk_fraction=Decimal("0.01"))
    auth = policy.authorize(candidate(score="0.8"), account(), quote)
    lower_score = policy.authorize(candidate(score="0.55"), account(), quote)
    assert auth.disposition is RiskDisposition.GRANTED
    assert auth.units == 50_000
    assert auth.risk_amount == Decimal("100.0000")
    assert lower_score.units == auth.units
    assert lower_score.risk_amount == auth.risk_amount


def test_optional_score_scaling_can_only_reduce_risk() -> None:
    quote = Quote("EUR_USD", Decimal("1.1"), Decimal("1.1001"), datetime.now(UTC))
    policy = RiskPolicy(risk_fraction=Decimal("0.01"), scale_risk_by_score=True)
    high = policy.authorize(candidate(score="1"), account(), quote)
    lower = policy.authorize(candidate(score="0.6"), account(), quote)
    assert lower.risk_amount <= high.risk_amount


def test_risk_denies_cross_without_conversion() -> None:
    quote = Quote("EUR_GBP", Decimal("0.85"), Decimal("0.8501"), datetime.now(UTC))
    auth = RiskPolicy().authorize(candidate("EUR_GBP"), account(), quote)
    assert auth.disposition is RiskDisposition.DENIED


def test_risk_denies_daily_marked_loss_limit() -> None:
    quote = Quote("EUR_USD", Decimal("1.1"), Decimal("1.1001"), datetime.now(UTC))
    realized = RiskPolicy().authorize(candidate(), account(realized_pl_today=Decimal("-250")), quote)
    unrealized = RiskPolicy().authorize(candidate(), account(unrealized_pl=Decimal("-250")), quote)
    assert realized.disposition is RiskDisposition.DENIED
    assert unrealized.disposition is RiskDisposition.DENIED


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


def test_cross_currency_risk_uses_conversion_rate() -> None:
    cross_candidate = TradeCandidate(
        candidate_id=uuid4(),
        instrument="EUR_GBP",
        direction=Direction.LONG,
        disposition=DecisionDisposition.TRADE,
        score=Decimal("0.8"),
        entry_price=Decimal("0.8500"),
        stop_loss=Decimal("0.8450"),
        take_profit=Decimal("0.8600"),
        technical_score=Decimal("0.8"),
        fundamental_score=Decimal("0.7"),
        reasons=(),
    )
    snapshot = AccountSnapshot("A", "USD", Decimal("100000"), Decimal("100000"))
    quote = Quote("EUR_GBP", Decimal("0.8499"), Decimal("0.8501"), datetime.now(UTC))
    policy = RiskPolicy(max_units=1_000_000)
    authorization = policy.authorize(
        cross_candidate,
        snapshot,
        quote,
        conversion_rate=lambda source, target: Decimal("1.25") if (source, target) == ("GBP", "USD") else Decimal("1"),
    )
    assert authorization.disposition is RiskDisposition.GRANTED
    assert authorization.risk_amount <= Decimal("150")


def test_portfolio_currency_exposure_can_veto_trade() -> None:
    from forex_trader.domain.portfolio import OpenPosition

    trade = TradeCandidate(
        candidate_id=uuid4(),
        instrument="EUR_USD",
        direction=Direction.LONG,
        disposition=DecisionDisposition.TRADE,
        score=Decimal("1"),
        entry_price=Decimal("1.10"),
        stop_loss=Decimal("1.099"),
        take_profit=Decimal("1.102"),
        technical_score=Decimal("1"),
        fundamental_score=Decimal("1"),
        reasons=(),
    )
    snapshot = AccountSnapshot("A", "USD", Decimal("10000"), Decimal("10000"), open_position_count=1)
    quote = Quote("EUR_USD", Decimal("1.0999"), Decimal("1.1001"), datetime.now(UTC))
    policy = RiskPolicy(
        max_open_positions=3,
        max_units=100000,
        max_currency_exposure_fraction=Decimal("0.5"),
        max_gross_exposure_fraction=Decimal("2"),
    )
    authorization = policy.authorize(
        trade,
        snapshot,
        quote,
        positions=[OpenPosition("GBP_USD", long_units=Decimal("5000"), long_average_price=Decimal("1.25"))],
        conversion_rate=lambda source, target: Decimal("1") if source == target else Decimal("1.1"),
        mark_price=lambda instrument: Decimal("1.25") if instrument == "GBP_USD" else Decimal("1.10"),
    )
    assert authorization.disposition is RiskDisposition.DENIED
    assert "exposure" in authorization.reasons[0]


def test_portfolio_exposure_fails_closed_when_existing_position_cannot_be_priced() -> None:
    from forex_trader.domain.portfolio import OpenPosition

    quote = Quote("EUR_USD", Decimal("1.1"), Decimal("1.1001"), datetime.now(UTC))
    auth = RiskPolicy(max_open_positions=3).authorize(
        candidate(),
        account(open_position_count=1),
        quote,
        positions=[OpenPosition("GBP_JPY", long_units=Decimal("1000"))],
        conversion_rate=lambda source, target: Decimal("1") if source == target else None,
        mark_price=lambda instrument: None,
    )
    assert auth.disposition is RiskDisposition.DENIED
    assert "cannot be priced safely" in auth.reasons[0]


def test_margin_reserve_can_veto_trade() -> None:
    quote = Quote("EUR_USD", Decimal("1.1"), Decimal("1.1001"), datetime.now(UTC))
    snapshot = account(margin_available=Decimal("100"))
    auth = RiskPolicy(
        risk_fraction=Decimal("0.01"),
        max_units=100000,
        max_gross_exposure_fraction=Decimal("100"),
        max_currency_exposure_fraction=Decimal("100"),
    ).authorize(
        candidate(),
        snapshot,
        quote,
        positions=[],
        conversion_rate=lambda source, target: Decimal("1"),
        margin_rate=Decimal("0.10"),
    )
    assert auth.disposition is RiskDisposition.DENIED
    assert "margin" in auth.reasons[0]
