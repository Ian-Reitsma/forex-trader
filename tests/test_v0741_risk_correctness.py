from __future__ import annotations

from datetime import datetime
from decimal import Decimal

import pytest

from forex_trader.application.risk_breaker import (
    review_loss_streak_breaker,
    risk_breaker_review_key,
    risk_breaker_resume_cursor,
    risk_breaker_state_key,
    risk_breaker_status,
)
from forex_trader.application.sync import (
    _parse_realized_pl,
    _realized_fill_pl,
    _strategy_owned_realized_outcomes,
    _transaction_id_key,
)
from forex_trader.domain.macro_factor_risk import (
    SUPPORTED_EIGHT_CURRENCY_PAIRS,
    default_macro_factor_map,
)
from forex_trader.infrastructure.advanced_repository import AdvancedTradingRepository


def test_default_macro_factor_map_covers_all_28_supported_currency_pairs() -> None:
    factor_map = default_macro_factor_map()
    assert len(factor_map) == 28
    assert set(factor_map) == set(SUPPORTED_EIGHT_CURRENCY_PAIRS)
    assert set(factor_map["AUD_CHF"]) == {
        "aud_macro",
        "aud_rates",
        "chf_macro",
        "chf_rates",
        "commodity_cycle",
    }
    assert "commodity_cycle" not in factor_map["EUR_CHF"]


def test_breaker_review_is_fail_closed_auditable_and_establishes_resume_cursor() -> None:
    repository = AdvancedTradingRepository(":memory:")
    nav = Decimal("10000")
    for _ in range(6):
        repository.update_advanced_risk_state(
            account_id="acct",
            nav=nav,
            realized_loss=True,
        )

    before = risk_breaker_status(
        repository,
        account_id="acct",
        nav=nav,
        max_loss_streak=6,
    )
    assert before["blocked"] is True
    assert before["state"] == "review_required"

    review = review_loss_streak_breaker(
        repository,
        account_id="acct",
        nav=nav,
        max_loss_streak=6,
        broker_cursor="49",
        review_id="review-1",
        reason="reviewed six owned Practice losses",
    )
    assert review["previous_loss_streak"] == 6
    assert risk_breaker_resume_cursor(repository, "acct") == "49"
    assert repository.runtime_state(risk_breaker_review_key("acct", "review-1")) is not None

    with pytest.raises(ValueError, match="already been used"):
        review_loss_streak_breaker(
            repository,
            account_id="acct",
            nav=nav,
            max_loss_streak=6,
            broker_cursor="49",
            review_id="review-1",
            reason="duplicate review must not overwrite audit history",
        )


def test_breaker_review_rejects_untripped_state_and_naive_timestamp() -> None:
    repository = AdvancedTradingRepository(":memory:")
    nav = Decimal("10000")
    with pytest.raises(ValueError, match="not tripped"):
        review_loss_streak_breaker(
            repository,
            account_id="acct",
            nav=nav,
            max_loss_streak=6,
            broker_cursor="49",
            review_id="review-1",
            reason="should fail",
        )

    for _ in range(6):
        repository.update_advanced_risk_state(
            account_id="acct",
            nav=nav,
            realized_loss=True,
        )
    with pytest.raises(ValueError, match="timezone-aware"):
        review_loss_streak_breaker(
            repository,
            account_id="acct",
            nav=nav,
            max_loss_streak=6,
            broker_cursor="49",
            review_id="review-2",
            reason="naive time should fail",
            reviewed_at=datetime(2026, 8, 12, 19, 0),
        )


def test_breaker_input_validation_and_observational_status_edges() -> None:
    repository = AdvancedTradingRepository(":memory:")
    nav = Decimal("10000")

    with pytest.raises(ValueError, match="account_id"):
        risk_breaker_state_key("   ")
    with pytest.raises(ValueError, match="account_id"):
        risk_breaker_review_key("", "review")
    with pytest.raises(ValueError, match="review_id"):
        risk_breaker_review_key("acct", "  ")
    with pytest.raises(ValueError, match="positive"):
        risk_breaker_status(repository, account_id="acct", nav=nav, max_loss_streak=0)

    class NoRuntimeState:
        pass

    assert risk_breaker_resume_cursor(NoRuntimeState(), "acct") is None
    repository.set_runtime_state(risk_breaker_state_key("acct"), {"state": "resume_authorized"})
    assert risk_breaker_resume_cursor(repository, "acct") is None

    for review_id, reason, cursor, maximum, message in (
        ("", "reason", "49", 6, "review_id"),
        ("review", "", "49", 6, "review reason"),
        ("review", "reason", "", 6, "broker_cursor"),
        ("review", "reason", "49", 0, "positive"),
    ):
        with pytest.raises(ValueError, match=message):
            review_loss_streak_breaker(
                repository,
                account_id="acct",
                nav=nav,
                max_loss_streak=maximum,
                broker_cursor=cursor,
                review_id=review_id,
                reason=reason,
            )


def test_owned_outcome_helpers_fail_closed_and_ignore_unowned_shapes() -> None:
    with pytest.raises(ValueError, match="missing its id"):
        _strategy_owned_realized_outcomes([{"type": "ORDER_FILL", "pl": "1"}])

    transactions: list[dict[str, object]] = [
        {"id": "1", "type": "MARKET_ORDER", "clientExtensions": "not-a-mapping"},
        {"id": "2", "type": "MARKET_ORDER", "clientExtensions": {"id": "manual", "tag": "forex-trader"}},
        {"id": "3", "type": "ORDER_FILL", "orderID": "2", "tradeOpened": "bad"},
        {"id": "4", "type": "ORDER_FILL", "tradesClosed": "bad", "pl": "5"},
        {"id": "5", "type": "ORDER_FILL", "tradesClosed": ["bad", {"tradeID": "unknown", "realizedPL": "9"}]},
    ]
    assert _strategy_owned_realized_outcomes(transactions) == []

    owned = [
        {"id": "10", "type": "MARKET_ORDER", "clientExtensions": {"id": "ft-owned", "tag": "forex-trader"}},
        {"id": "11", "type": "ORDER_FILL", "orderID": "10", "tradeOpened": {"tradeID": "t-1"}, "pl": "0"},
        {"id": "12", "type": "ORDER_FILL", "pl": "-2.5", "tradesClosed": [{"tradeID": "t-1", "realizedPL": None}]},
    ]
    assert _strategy_owned_realized_outcomes(owned) == [("12", Decimal("-2.5"))]


def test_realized_pl_and_transaction_key_parsers_cover_fail_closed_edges() -> None:
    assert _realized_fill_pl({"id": "1", "type": "MARKET_ORDER", "pl": "1"}) is None
    assert _realized_fill_pl({"id": "2", "type": "ORDER_FILL", "pl": ""}) is None
    assert _realized_fill_pl({"id": "3", "type": "ORDER_FILL", "pl": "1.25"}) == Decimal("1.25")

    with pytest.raises(ValueError, match="missing realized pl"):
        _parse_realized_pl(None, "4")
    with pytest.raises(ValueError, match="non-finite"):
        _parse_realized_pl("NaN", "5")

    assert _transaction_id_key("49") == (0, 49)
    assert _transaction_id_key("opaque") == (1, "opaque")
    with pytest.raises(ValueError, match="cannot be empty"):
        _transaction_id_key("  ")
