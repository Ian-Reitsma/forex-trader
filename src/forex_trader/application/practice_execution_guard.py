from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Mapping

from forex_trader.application.autonomous import AutonomousCycleReport, AutonomousPracticeRuntime
from forex_trader.config import AppConfig


@dataclass(frozen=True, slots=True)
class PracticeExecutionGateStatus:
    """Durable, fail-closed execution gate for the Practice autonomous runtime.

    The gate suppresses broker submissions while deliberately preserving the full
    research/evaluation loop. That means a losing epoch can keep producing decision,
    readiness and counterfactual risk evidence without placing another order.
    """

    observed_at: datetime
    blocked: bool
    reason: str
    loss_streak: int | None
    execution_loss_streak_limit: int
    configured_max_new_orders_per_cycle: int
    effective_max_new_orders_per_cycle: int
    pre_gate_sync_inserted: int | None
    pre_gate_sync_error: str | None
    promotion_closed_trades: int | None
    promotion_wins: int | None
    promotion_total_pl: str | None

    def to_jsonable(self) -> dict[str, object]:
        return {
            "schema": "practice-execution-gate-v1",
            "observed_at": self.observed_at.astimezone(UTC).isoformat(),
            "blocked": self.blocked,
            "reason": self.reason,
            "loss_streak": self.loss_streak,
            "execution_loss_streak_limit": self.execution_loss_streak_limit,
            "configured_max_new_orders_per_cycle": self.configured_max_new_orders_per_cycle,
            "effective_max_new_orders_per_cycle": self.effective_max_new_orders_per_cycle,
            "pre_gate_sync_inserted": self.pre_gate_sync_inserted,
            "pre_gate_sync_error": self.pre_gate_sync_error,
            "promotion_closed_trades": self.promotion_closed_trades,
            "promotion_wins": self.promotion_wins,
            "promotion_total_pl": self.promotion_total_pl,
            "behavior": "broker submissions suppressed when blocked; pair evaluation and evidence capture continue",
        }


class EvidenceGuardedAutonomousPracticeRuntime(AutonomousPracticeRuntime):
    """Autonomous Practice runtime with a stricter research-epoch execution gate.

    The underlying risk policy remains authoritative. This wrapper adds an earlier
    loss-streak execution stop at three consecutive realized strategy losses by
    default. It never increases order count, units, risk fraction or broker authority.
    """

    GUARD_STATE_KEY = "practice_execution_guard"

    def __init__(
        self,
        config: AppConfig,
        *,
        all_currency_pairs: bool = True,
        max_new_orders_per_cycle: int = 1,
        execution_loss_streak_limit: int = 3,
        interval_seconds: float | None = None,
        fundamental_refresh_seconds: float = 3600.0,
        universe_refresh_seconds: float = 3600.0,
        evidence_path: str | Path = "autonomous-campaign-evidence.jsonl",
        decision_evidence_path: str | Path = "autonomous-decision-evidence.jsonl",
    ) -> None:
        if execution_loss_streak_limit < 1:
            raise ValueError("execution_loss_streak_limit must be positive")
        super().__init__(
            config,
            all_currency_pairs=all_currency_pairs,
            max_new_orders_per_cycle=max_new_orders_per_cycle,
            interval_seconds=interval_seconds,
            fundamental_refresh_seconds=fundamental_refresh_seconds,
            universe_refresh_seconds=universe_refresh_seconds,
            evidence_path=evidence_path,
            decision_evidence_path=decision_evidence_path,
        )
        self.execution_loss_streak_limit = min(
            execution_loss_streak_limit,
            config.max_loss_streak,
        )
        self._configured_max_new_orders_per_cycle = max_new_orders_per_cycle
        self._guard_status: PracticeExecutionGateStatus | None = None

    @property
    def guard_status(self) -> PracticeExecutionGateStatus | None:
        return self._guard_status

    def run_cycle(self, cycle: int) -> AutonomousCycleReport:
        # Reconcile once before deciding whether this cycle may submit. The parent
        # runtime reconciles again; that second pass is intentionally idempotent and
        # ensures its normal evidence/readiness semantics remain unchanged.
        pre_gate_sync_inserted: int | None = None
        pre_gate_sync_error: str | None = None
        try:
            pre_gate_sync_inserted = self.synchronizer.catch_up()
        except Exception as exc:  # fail closed; parent runtime will retry and report it
            pre_gate_sync_error = f"{type(exc).__name__}: {exc}"

        status = self._assess_execution_gate(
            pre_gate_sync_inserted=pre_gate_sync_inserted,
            pre_gate_sync_error=pre_gate_sync_error,
        )
        self._guard_status = status
        self.repository.set_runtime_state(self.GUARD_STATE_KEY, status.to_jsonable())

        configured = self.max_new_orders_per_cycle
        self.max_new_orders_per_cycle = status.effective_max_new_orders_per_cycle
        try:
            report = super().run_cycle(cycle)
        finally:
            self.max_new_orders_per_cycle = configured

        # Refresh the durable status after the parent's post-cycle reconciliation so
        # the UI/diagnostics see the latest realized-loss state even before next cycle.
        final_status = self._assess_execution_gate(
            pre_gate_sync_inserted=pre_gate_sync_inserted,
            pre_gate_sync_error=pre_gate_sync_error,
        )
        self._guard_status = final_status
        self.repository.set_runtime_state(self.GUARD_STATE_KEY, final_status.to_jsonable())
        return report

    def _assess_execution_gate(
        self,
        *,
        pre_gate_sync_inserted: int | None,
        pre_gate_sync_error: str | None,
    ) -> PracticeExecutionGateStatus:
        observed_at = self.clock().astimezone(UTC)
        loss_streak: int | None = None
        blocked = False
        reason = "execution research epoch is inside its loss-streak allowance"

        if pre_gate_sync_error is not None:
            blocked = True
            reason = f"pre-gate reconciliation failed; execution suppressed: {pre_gate_sync_error}"
        else:
            try:
                account = self.engine.broker.account()
                state_getter = getattr(self.repository, "advanced_risk_state", None)
                if not callable(state_getter):
                    blocked = True
                    reason = "durable advanced risk state is unavailable; execution suppressed"
                else:
                    raw_state = state_getter(account.account_id, account.nav)
                    if not isinstance(raw_state, Mapping):
                        blocked = True
                        reason = "durable advanced risk state returned an invalid payload; execution suppressed"
                    else:
                        loss_streak = int(str(raw_state.get("loss_streak", "0")))
                        if loss_streak >= self.execution_loss_streak_limit:
                            blocked = True
                            reason = (
                                f"realized strategy loss streak {loss_streak} reached the Practice research-epoch "
                                f"execution limit {self.execution_loss_streak_limit}; evaluations continue shadow-only"
                            )
            except Exception as exc:
                blocked = True
                reason = f"execution-gate risk state failed closed: {type(exc).__name__}: {exc}"

        closed_trades, wins, total_pl = self._promotion_snapshot()
        effective_orders = 0 if blocked else self._configured_max_new_orders_per_cycle
        return PracticeExecutionGateStatus(
            observed_at=observed_at,
            blocked=blocked,
            reason=reason,
            loss_streak=loss_streak,
            execution_loss_streak_limit=self.execution_loss_streak_limit,
            configured_max_new_orders_per_cycle=self._configured_max_new_orders_per_cycle,
            effective_max_new_orders_per_cycle=effective_orders,
            pre_gate_sync_inserted=pre_gate_sync_inserted,
            pre_gate_sync_error=pre_gate_sync_error,
            promotion_closed_trades=closed_trades,
            promotion_wins=wins,
            promotion_total_pl=total_pl,
        )

    def _promotion_snapshot(self) -> tuple[int | None, int | None, str | None]:
        try:
            status = self.engine.promotion_status()
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
