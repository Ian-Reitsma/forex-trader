from __future__ import annotations

from datetime import datetime
from decimal import Decimal

import pytest

from forex_trader.application.risk_breaker import (
    review_loss_streak_breaker,
    risk_breaker_review_key,
    risk_breaker_resume_cursor,
    risk_breaker_status,
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
