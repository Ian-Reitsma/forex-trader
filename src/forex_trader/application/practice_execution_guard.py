from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Mapping

from forex_trader.application.engine import TradingEngine


@dataclass(frozen=True, slots=True)
class PracticeExecutionGateStatus:
    """Read-only assessment of whether a Practice research epoch warrants review.

    This object has no broker-write authority. It lets diagnostics distinguish a
    mechanically healthy runtime from an execution epoch that has accumulated enough
    consecutive realized strategy losses to deserve operator review.
    """

    observed_at: datetime
    review_recommended: bool
    reason: str
    loss_streak: int | None
    review_loss_streak_limit: int
    promotion_closed_trades: int | None
    promotion_wins: int | None
    promotion_total_pl: str | None

    def to_jsonable(self) -> dict[str, object]:
        return {
            "schema": "practice-execution-gate-assessment-v1",
            "observed_at": self.observed_at.astimezone(UTC).isoformat(),
            "review_recommended": self.review_recommended,
            "reason": self.reason,
            "loss_streak": self.loss_streak,
            "review_loss_streak_limit": self.review_loss_streak_limit,
            "promotion_closed_trades": self.promotion_closed_trades,
            "promotion_wins": self.promotion_wins,
            "promotion_total_pl": self.promotion_total_pl,
            "broker_write_authority": False,
        }


def assess_practice_execution_gate(
    engine: TradingEngine,
    *,
    review_loss_streak_limit: int = 3,
) -> PracticeExecutionGateStatus:
    if review_loss_streak_limit < 1:
        raise ValueError("review_loss_streak_limit must be positive")

    observed_at = datetime.now(UTC)
    loss_streak: int | None = None
    review_recommended = False
    reason = "Practice research epoch remains below the review loss-streak threshold"

    try:
        account = engine.broker.account()
        state_getter = getattr(engine.repository, "advanced_risk_state", None)
        if not callable(state_getter):
            review_recommended = True
            reason = "durable advanced risk state is unavailable; operator review recommended"
        else:
            raw_state = state_getter(account.account_id, account.nav)
            if not isinstance(raw_state, Mapping):
                review_recommended = True
                reason = "durable advanced risk state returned an invalid payload; operator review recommended"
            else:
                loss_streak = int(str(raw_state.get("loss_streak", "0")))
                if loss_streak >= review_loss_streak_limit:
                    review_recommended = True
                    reason = (
                        f"realized strategy loss streak {loss_streak} reached the research-epoch "
                        f"review threshold {review_loss_streak_limit}"
                    )
    except Exception as exc:
        review_recommended = True
        reason = f"risk-state assessment failed closed: {type(exc).__name__}: {exc}"

    closed_trades, wins, total_pl = _promotion_snapshot(engine)
    return PracticeExecutionGateStatus(
        observed_at=observed_at,
        review_recommended=review_recommended,
        reason=reason,
        loss_streak=loss_streak,
        review_loss_streak_limit=review_loss_streak_limit,
        promotion_closed_trades=closed_trades,
        promotion_wins=wins,
        promotion_total_pl=total_pl,
    )


def _promotion_snapshot(engine: TradingEngine) -> tuple[int | None, int | None, str | None]:
    try:
        status = engine.promotion_status()
    except Exception:
        return None, None, None
    metrics = status.get("metrics") if isinstance(status, Mapping) else None
    if not isinstance(metrics, Mapping):
        return None, None, None
    closed_raw = metrics.get("closed_trades")
    wins_raw = metrics.get("wins")
    total_pl_raw = metrics.get("total_pl")
    try:
        closed = int(str(closed_raw)) if closed_raw is not None else None
    except ValueError:
        closed = None
    try:
        wins = int(str(wins_raw)) if wins_raw is not None else None
    except ValueError:
        wins = None
    total_pl = None if total_pl_raw is None else str(total_pl_raw)
    return closed, wins, total_pl
