from __future__ import annotations

import os
import time
from collections.abc import Callable, Mapping
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Protocol, cast
from uuid import uuid4

from forex_trader.application.campaign import CampaignCycleReport, PracticeCampaignRunner
from forex_trader.application.campaign_policy import (
    CampaignUniverseSelection,
    campaign_policy_context,
    select_campaign_universe,
)
from forex_trader.application.engine import TradingEngine
from forex_trader.application.free_official_sync import (
    FreeOfficialSyncReport,
    sync_free_official_fundamentals,
)
from forex_trader.application.sync import (
    BrokerStateSynchronizer,
    TransactionRepository,
    TransactionSource,
)
from forex_trader.config import AppConfig, build_engine
from forex_trader.domain.enums import OperatingMode, ProviderKind
from forex_trader.domain.macro_history import MacroObservation, PointInTimeFundamentalBook
from forex_trader.domain.timeframes import granularity_duration

RUNTIME_STATE_KEY = "autonomous_practice"


class RuntimeRepository(Protocol):
    def set_runtime_state(self, name: str, payload: Mapping[str, object]) -> None: ...

    def runtime_state(self, name: str) -> dict[str, object] | None: ...

    def get_broker_cursor(self, name: str) -> str | None: ...

    def macro_observations(self, *, as_of: datetime | None = None) -> list[MacroObservation]: ...


class BrokerSynchronizer(Protocol):
    def catch_up(self) -> int: ...


class FundamentalSynchronizer(Protocol):
    def __call__(self, database_path: str | Path) -> FreeOfficialSyncReport: ...


@dataclass(frozen=True, slots=True)
class AutonomousCycleReport:
    campaign_id: str
    cycle: int
    started_at: datetime
    finished_at: datetime
    source_universe: str
    discovered_count: int
    eligible_count: int
    excluded_count: int
    pre_sync_inserted: int
    post_sync_inserted: int
    broker_cursor: str | None
    fundamental_refresh: dict[str, object] | None
    campaign: dict[str, object] | None
    errors: tuple[str, ...]
    stop_reason: str | None

    @property
    def orders_unresolved(self) -> int:
        if self.campaign is None:
            return 0
        value = self.campaign.get("orders_unresolved")
        return value if isinstance(value, int) else 0

    def to_jsonable(self) -> dict[str, object]:
        payload = asdict(self)
        payload["started_at"] = self.started_at.isoformat()
        payload["finished_at"] = self.finished_at.isoformat()
        return payload


def _utc_now() -> datetime:
    return datetime.now(UTC)


class AutonomousPracticeRuntime:
    """Durable, fail-closed OANDA Practice orchestration.

    The API server is deliberately not the trading loop. This runtime owns the repeated
    all-pair/configured-pair evaluation cycle, broker reconciliation, official-fundamental
    refresh, universe refresh, evidence writing, and a durable heartbeat that another
    process (the API/frontend) can observe.
    """

    def __init__(
        self,
        config: AppConfig,
        *,
        all_currency_pairs: bool = True,
        max_new_orders_per_cycle: int = 1,
        interval_seconds: float | None = None,
        fundamental_refresh_seconds: float = 3600.0,
        universe_refresh_seconds: float = 3600.0,
        evidence_path: str | Path = "autonomous-campaign-evidence.jsonl",
        decision_evidence_path: str | Path = "autonomous-decision-evidence.jsonl",
        engine: TradingEngine | None = None,
        synchronizer: BrokerSynchronizer | None = None,
        fundamental_sync: FundamentalSynchronizer = sync_free_official_fundamentals,
        clock: Callable[[], datetime] = _utc_now,
        monotonic: Callable[[], float] = time.monotonic,
        sleeper: Callable[[float], None] = time.sleep,
    ) -> None:
        errors = config.validate()
        if errors:
            raise ValueError("; ".join(errors))
        if config.provider is not ProviderKind.OANDA:
            raise ValueError("autonomous Practice runtime requires FOREX_PROVIDER=oanda")
        if config.mode is not OperatingMode.PAPER or not config.enable_paper_orders:
            raise ValueError(
                "autonomous Practice runtime requires FOREX_MODE=paper and "
                "FOREX_ENABLE_PAPER_ORDERS=true"
            )
        if max_new_orders_per_cycle < 0:
            raise ValueError("max_new_orders_per_cycle cannot be negative")
        if interval_seconds is not None and interval_seconds < 0:
            raise ValueError("interval_seconds cannot be negative")
        if fundamental_refresh_seconds <= 0:
            raise ValueError("fundamental_refresh_seconds must be positive")
        if universe_refresh_seconds <= 0:
            raise ValueError("universe_refresh_seconds must be positive")

        resolved_engine = engine or build_engine(config)
        if not hasattr(resolved_engine.repository, "set_runtime_state"):
            raise TypeError("autonomous runtime requires durable runtime-state repository support")
        if not hasattr(resolved_engine.repository, "macro_observations"):
            raise TypeError("autonomous runtime requires durable macro-observation repository support")

        self.config = config
        self.engine = resolved_engine
        self.repository = cast(RuntimeRepository, resolved_engine.repository)
        self.synchronizer = synchronizer or BrokerStateSynchronizer(
            cast(TransactionSource, resolved_engine.broker),
            cast(TransactionRepository, resolved_engine.repository),
        )
        self.fundamental_sync = fundamental_sync
        self.all_currency_pairs = all_currency_pairs
        self.max_new_orders_per_cycle = max_new_orders_per_cycle
        self.interval_seconds = (
            granularity_duration(config.lower_timeframe).total_seconds()
            if interval_seconds is None
            else interval_seconds
        )
        self.fundamental_refresh_seconds = fundamental_refresh_seconds
        self.universe_refresh_seconds = universe_refresh_seconds
        self.evidence_path = Path(evidence_path)
        self.decision_evidence_path = Path(decision_evidence_path)
        self.clock = clock
        self.monotonic = monotonic
        self.sleeper = sleeper

        self.campaign_id = uuid4().hex
        self.started_at = self.clock().astimezone(UTC)
        self._last_fundamental_refresh_monotonic: float | None = None
        self._last_universe_refresh_monotonic: float | None = None
        self._last_fundamental_refresh: dict[str, object] | None = None
        self._last_fundamental_error: str | None = None
        self._discovered: tuple[str, ...] = ()
        self._last_report: AutonomousCycleReport | None = None

    def run_cycle(self, cycle: int) -> AutonomousCycleReport:
        if cycle < 1:
            raise ValueError("cycle must be positive")
        started = self.clock().astimezone(UTC)
        errors: list[str] = []
        pre_sync_inserted = 0
        post_sync_inserted = 0
        selection: CampaignUniverseSelection | None = None
        campaign_report: CampaignCycleReport | None = None
        stop_reason: str | None = None

        self._write_runtime_state(
            active=True,
            status="running",
            cycle=cycle,
            heartbeat_at=started,
            selection=None,
            errors=(),
        )

        try:
            pre_sync_inserted = self.synchronizer.catch_up()
        except Exception as exc:
            errors.append(f"broker pre-cycle reconciliation failed: {type(exc).__name__}: {exc}")
        else:
            self._refresh_fundamentals_if_due(errors)
            try:
                selection = self._select_universe()
            except Exception as exc:
                errors.append(f"universe refresh failed: {type(exc).__name__}: {exc}")

            if selection is not None and selection.selected:
                metadata = {
                    "runtime": "autonomous_practice",
                    "source": "broker" if self.all_currency_pairs else "configured",
                    "discovered_count": len(selection.discovered),
                    "eligible_count": len(selection.selected),
                    "excluded_count": selection.excluded_count,
                    "fundamental_preflight": bool(self.config.require_fundamentals),
                    "official_fundamental_refresh": self._last_fundamental_refresh,
                }
                runner = PracticeCampaignRunner(
                    self.engine,
                    selection.selected,
                    execute=True,
                    max_new_orders_per_cycle=self.max_new_orders_per_cycle,
                    stop_on_unresolved=True,
                    evidence_path=self.evidence_path,
                    decision_evidence_path=self.decision_evidence_path,
                    campaign_id=self.campaign_id,
                    policy_context=campaign_policy_context(self.engine),
                    campaign_metadata=metadata,
                )
                campaign_report = runner.run_cycle(cycle)
                if campaign_report.orders_unresolved:
                    stop_reason = (
                        campaign_report.stop_reason
                        or "unresolved broker order state requires operator reconciliation"
                    )
            elif selection is not None:
                errors.append(
                    "no instruments currently satisfy the fundamental-coverage preflight; "
                    "execution remains fail-closed"
                )

            try:
                post_sync_inserted = self.synchronizer.catch_up()
            except Exception as exc:
                errors.append(f"broker post-cycle reconciliation failed: {type(exc).__name__}: {exc}")

        finished = self.clock().astimezone(UTC)
        report = AutonomousCycleReport(
            campaign_id=self.campaign_id,
            cycle=cycle,
            started_at=started,
            finished_at=finished,
            source_universe="broker" if self.all_currency_pairs else "configured",
            discovered_count=len(selection.discovered) if selection is not None else len(self._discovered),
            eligible_count=len(selection.selected) if selection is not None else 0,
            excluded_count=selection.excluded_count if selection is not None else 0,
            pre_sync_inserted=pre_sync_inserted,
            post_sync_inserted=post_sync_inserted,
            broker_cursor=self.repository.get_broker_cursor("oanda.transactions"),
            fundamental_refresh=self._last_fundamental_refresh,
            campaign=campaign_report.to_jsonable() if campaign_report is not None else None,
            errors=tuple(errors),
            stop_reason=stop_reason,
        )
        self._last_report = report
        status = "halted" if report.orders_unresolved else "degraded" if errors else "running"
        self._write_runtime_state(
            active=not bool(report.orders_unresolved),
            status=status,
            cycle=cycle,
            heartbeat_at=finished,
            selection=selection,
            errors=tuple(errors),
        )
        return report

    def run(
        self,
        *,
        max_cycles: int | None = None,
        on_cycle: Callable[[AutonomousCycleReport], None] | None = None,
    ) -> tuple[AutonomousCycleReport, ...]:
        if max_cycles is not None and max_cycles < 1:
            raise ValueError("max_cycles must be positive when supplied")

        finite_reports: list[AutonomousCycleReport] = []
        cycle = 0
        self._write_runtime_state(
            active=True,
            status="starting",
            cycle=0,
            heartbeat_at=self.clock().astimezone(UTC),
            selection=None,
            errors=(),
        )
        try:
            while max_cycles is None or cycle < max_cycles:
                cycle += 1
                cycle_started = self.monotonic()
                report = self.run_cycle(cycle)
                if max_cycles is not None:
                    finite_reports.append(report)
                if on_cycle is not None:
                    on_cycle(report)
                if report.orders_unresolved:
                    break
                if max_cycles is not None and cycle >= max_cycles:
                    break
                elapsed = self.monotonic() - cycle_started
                self.sleeper(max(0.0, self.interval_seconds - elapsed))
        finally:
            final_errors = self._last_report.errors if self._last_report is not None else ()
            final_status = (
                "halted"
                if self._last_report is not None and self._last_report.orders_unresolved
                else "stopped"
            )
            self._write_runtime_state(
                active=False,
                status=final_status,
                cycle=cycle,
                heartbeat_at=self.clock().astimezone(UTC),
                selection=None,
                errors=final_errors,
            )
        return tuple(finite_reports)

    def _refresh_fundamentals_if_due(self, errors: list[str]) -> None:
        if not self.config.require_fundamentals:
            return
        now_mono = self.monotonic()
        if (
            self._last_fundamental_refresh_monotonic is not None
            and now_mono - self._last_fundamental_refresh_monotonic
            < self.fundamental_refresh_seconds
        ):
            return
        self._last_fundamental_refresh_monotonic = now_mono
        try:
            report = self.fundamental_sync(self.config.database_path)
        except Exception as exc:
            self._last_fundamental_error = f"{type(exc).__name__}: {exc}"
            errors.append(f"official fundamental refresh failed: {self._last_fundamental_error}")
            return

        self._last_fundamental_refresh = report.to_jsonable()
        self._last_fundamental_error = None
        if not report.healthy:
            errors.append(
                "official fundamental refresh is degraded; pair-level confidence preflight remains authoritative"
            )

        if isinstance(self.engine.fundamentals, PointInTimeFundamentalBook):
            self.engine.fundamentals.replace_observations(self.repository.macro_observations())

    def _select_universe(self) -> CampaignUniverseSelection:
        now_mono = self.monotonic()
        if (
            not self._discovered
            or self._last_universe_refresh_monotonic is None
            or now_mono - self._last_universe_refresh_monotonic >= self.universe_refresh_seconds
        ):
            discovered = (
                tuple(self.engine.instrument_universe())
                if self.all_currency_pairs
                else tuple(self.config.instruments)
            )
            if not discovered:
                raise RuntimeError("instrument universe is empty")
            self._discovered = tuple(
                dict.fromkeys(item.strip().upper() for item in discovered if item.strip())
            )
            self._last_universe_refresh_monotonic = now_mono

        return select_campaign_universe(
            self.engine,
            list(self._discovered),
            require_fundamental_coverage=bool(self.config.require_fundamentals),
            as_of=self.clock().astimezone(UTC),
        )

    def _write_runtime_state(
        self,
        *,
        active: bool,
        status: str,
        cycle: int,
        heartbeat_at: datetime,
        selection: CampaignUniverseSelection | None,
        errors: tuple[str, ...],
    ) -> None:
        if heartbeat_at.tzinfo is None:
            raise ValueError("heartbeat_at must be timezone-aware")
        selected_count = (
            len(selection.selected)
            if selection is not None
            else self._last_report.eligible_count
            if self._last_report is not None
            else 0
        )
        discovered_count = len(selection.discovered) if selection is not None else len(self._discovered)
        payload: dict[str, object] = {
            "schema": "autonomous-practice-runtime-v1",
            "active": active,
            "status": status,
            "pid": os.getpid(),
            "campaign_id": self.campaign_id,
            "started_at": self.started_at.isoformat(),
            "heartbeat_at": heartbeat_at.astimezone(UTC).isoformat(),
            "cycle": cycle,
            "execute": True,
            "source_universe": "broker" if self.all_currency_pairs else "configured",
            "interval_seconds": self.interval_seconds,
            "fundamental_refresh_seconds": self.fundamental_refresh_seconds,
            "universe_refresh_seconds": self.universe_refresh_seconds,
            "discovered_count": discovered_count,
            "eligible_count": selected_count,
            "excluded_count": (
                selection.excluded_count
                if selection is not None
                else self._last_report.excluded_count
                if self._last_report is not None
                else 0
            ),
            "broker_cursor": self.repository.get_broker_cursor("oanda.transactions"),
            "last_fundamental_refresh": self._last_fundamental_refresh,
            "last_fundamental_error": self._last_fundamental_error,
            "errors": list(errors),
        }
        if self._last_report is not None:
            payload["last_cycle"] = self._last_report.to_jsonable()
        self.repository.set_runtime_state(RUNTIME_STATE_KEY, payload)
