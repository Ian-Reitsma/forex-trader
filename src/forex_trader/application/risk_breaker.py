from __future__ import annotations

from collections.abc import Mapping
from datetime import UTC, datetime
from decimal import Decimal
from typing import Protocol

RISK_BREAKER_STATE_PREFIX = "risk_breaker:"


class RiskBreakerRepository(Protocol):
    def advanced_risk_state(self, account_id: str, nav: Decimal) -> dict[str, object]: ...

    def runtime_state(self, name: str) -> dict[str, object] | None: ...

    def set_runtime_state(self, name: str, payload: Mapping[str, object]) -> None: ...


def risk_breaker_state_key(account_id: str) -> str:
    if not account_id.strip():
        raise ValueError("account_id is required")
    return f"{RISK_BREAKER_STATE_PREFIX}{account_id.strip()}"


def risk_breaker_resume_cursor(repository: object, account_id: str) -> str | None:
    reader = getattr(repository, "runtime_state", None)
    if reader is None:
        return None
    payload = reader(risk_breaker_state_key(account_id))
    if not isinstance(payload, dict):
        return None
    cursor = str(payload.get("resume_after_transaction_id") or "").strip()
    return cursor or None


def risk_breaker_status(
    repository: RiskBreakerRepository,
    *,
    account_id: str,
    nav: Decimal,
    max_loss_streak: int,
) -> dict[str, object]:
    if max_loss_streak < 1:
        raise ValueError("max_loss_streak must be positive")
    state = repository.advanced_risk_state(account_id, nav)
    loss_streak = int(str(state.get("loss_streak", "0")))
    review = repository.runtime_state(risk_breaker_state_key(account_id))
    breaker_state = "review_required" if loss_streak >= max_loss_streak else "normal"
    if breaker_state == "normal" and isinstance(review, dict):
        breaker_state = "resumed_after_review"
    return {
        "account_id": account_id,
        "state": breaker_state,
        "loss_streak": loss_streak,
        "maximum_loss_streak": max_loss_streak,
        "blocked": loss_streak >= max_loss_streak,
        "advanced_risk": state,
        "latest_review": review,
    }


def review_loss_streak_breaker(
    repository: RiskBreakerRepository,
    *,
    account_id: str,
    nav: Decimal,
    max_loss_streak: int,
    broker_cursor: str,
    review_id: str,
    reason: str,
    reviewed_at: datetime | None = None,
) -> dict[str, object]:
    clean_review_id = review_id.strip()
    clean_reason = reason.strip()
    clean_cursor = broker_cursor.strip()
    if not clean_review_id:
        raise ValueError("review_id is required")
    if not clean_reason:
        raise ValueError("review reason is required")
    if not clean_cursor:
        raise ValueError("broker_cursor is required")
    if max_loss_streak < 1:
        raise ValueError("max_loss_streak must be positive")

    current = repository.advanced_risk_state(account_id, nav)
    loss_streak = int(str(current.get("loss_streak", "0")))
    if loss_streak < max_loss_streak:
        raise ValueError(
            f"loss-streak breaker is not tripped: {loss_streak} < {max_loss_streak}"
        )

    observed = (reviewed_at or datetime.now(UTC)).astimezone(UTC)
    payload: dict[str, object] = {
        "schema": "loss-streak-breaker-review-v1",
        "account_id": account_id,
        "state": "resume_authorized",
        "review_id": clean_review_id,
        "reason": clean_reason,
        "previous_loss_streak": loss_streak,
        "resume_after_transaction_id": clean_cursor,
        "reviewed_at": observed.isoformat(),
    }
    repository.set_runtime_state(risk_breaker_state_key(account_id), payload)
    return payload
