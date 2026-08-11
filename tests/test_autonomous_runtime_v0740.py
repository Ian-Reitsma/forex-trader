from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

import pytest
from types import SimpleNamespace

from forex_trader.application.autonomous import AutonomousPracticeRuntime
from forex_trader.application.campaign_policy import CampaignUniverseSelection
from forex_trader.application.free_official_sync import FreeOfficialSyncReport
from forex_trader.config import AppConfig
from forex_trader.domain.enums import OperatingMode, ProviderKind
from forex_trader.infrastructure.repository import SqliteDecisionRepository
from forex_trader.infrastructure.trading_repository import TradingRepository


def _config(tmp_path) -> AppConfig:  # type: ignore[no-untyped-def]
    return AppConfig(
        provider=ProviderKind.OANDA,
        mode=OperatingMode.PAPER,
        database_path=str(tmp_path / "runtime.db"),
        instruments=("EUR_USD",),
        enable_paper_orders=True,
        oanda_token="test-token",
        oanda_account_id="test-account",
    )


def test_runtime_state_is_durable_and_replaceable() -> None:
    repository = TradingRepository(":memory:")
    repository.set_runtime_state(
        "autonomous_practice",
        {"active": True, "heartbeat_at": "2026-08-11T01:00:00+00:00", "cycle": 4},
    )
    first = repository.runtime_state("autonomous_practice")
    assert first is not None
    assert first["active"] is True
    assert first["cycle"] == 4
    assert "updated_at" in first

    repository.set_runtime_state(
        "autonomous_practice",
        {"active": False, "heartbeat_at": "2026-08-11T01:05:00+00:00", "cycle": 5},
    )
    second = repository.runtime_state("autonomous_practice")
    assert second is not None
    assert second["active"] is False
    assert second["cycle"] == 5


def test_promotion_excludes_probe_and_attributes_daily_financing() -> None:
    repository = SqliteDecisionRepository(":memory:")

    repository.save_broker_transaction(
        {
            "id": "4",
            "type": "MARKET_ORDER",
            "clientExtensions": {"id": "probe-capability", "tag": "forex-trader"},
        }
    )
    repository.save_broker_transaction(
        {"id": "5", "type": "ORDER_FILL", "orderID": "4", "tradeOpened": {"tradeID": "probe-trade"}}
    )
    repository.save_broker_transaction(
        {
            "id": "9",
            "type": "ORDER_FILL",
            "tradesClosed": [{"tradeID": "probe-trade", "realizedPL": "-0.0002", "financing": "0"}],
        }
    )

    repository.save_broker_transaction(
        {
            "id": "12",
            "type": "MARKET_ORDER",
            "clientExtensions": {"id": "ft-strategy-order", "tag": "forex-trader"},
        }
    )
    repository.save_broker_transaction(
        {"id": "13", "type": "ORDER_FILL", "orderID": "12", "tradeOpened": {"tradeID": "13"}}
    )
    repository.save_broker_transaction(
        {
            "id": "16",
            "type": "DAILY_FINANCING",
            "financing": "7.8082",
            "positionFinancings": [
                {
                    "instrument": "USD_CHF",
                    "openTradeFinancings": [{"tradeID": "13", "financing": "7.8082"}],
                }
            ],
        }
    )
    repository.save_broker_transaction(
        {
            "id": "17",
            "type": "ORDER_FILL",
            "orderID": "15",
            "tradesClosed": [{"tradeID": "13", "realizedPL": "-86.0301", "financing": "0"}],
        }
    )

    metrics = repository.promotion_metrics()
    assert metrics.closed_trades == 1
    assert metrics.wins == 0
    assert metrics.total_pl == Decimal("-78.2219")
    assert metrics.gross_loss == Decimal("78.2219")


class _FakeRepository:
    def __init__(self) -> None:
        self.states: list[dict[str, object]] = []
        self.cursor = "18"
        self.lease_owner: str | None = None

    def set_runtime_state(self, name: str, payload) -> None:  # type: ignore[no-untyped-def]
        assert name == "autonomous_practice"
        self.states.append(dict(payload))

    def runtime_state(self, name: str):  # type: ignore[no-untyped-def]
        return self.states[-1] if self.states else None

    def get_broker_cursor(self, name: str) -> str | None:
        assert name == "oanda.transactions"
        return self.cursor

    def acquire_runtime_lease(
        self, name: str, owner: str, *, ttl_seconds: float
    ) -> bool:
        assert name == "autonomous_practice"
        assert ttl_seconds > 0
        if self.lease_owner is not None:
            return False
        self.lease_owner = owner
        return True

    def renew_runtime_lease(
        self, name: str, owner: str, *, ttl_seconds: float
    ) -> bool:
        assert name == "autonomous_practice"
        assert ttl_seconds > 0
        return self.lease_owner == owner

    def runtime_lease_owner(self, name: str) -> str | None:
        assert name == "autonomous_practice"
        return self.lease_owner

    def release_runtime_lease(self, name: str, owner: str) -> None:
        assert name == "autonomous_practice"
        if self.lease_owner == owner:
            self.lease_owner = None

    def macro_observations(self, *, as_of=None):  # type: ignore[no-untyped-def]
        return []


class _FakeSynchronizer:
    def __init__(self) -> None:
        self.calls = 0

    def catch_up(self) -> int:
        self.calls += 1
        return 1 if self.calls == 1 else 0


class _FakeCampaignRunner:
    seen_instruments: tuple[str, ...] = ()

    def __init__(self, engine, instruments, **kwargs) -> None:  # type: ignore[no-untyped-def]
        type(self).seen_instruments = tuple(instruments)

    def run_cycle(self, cycle: int):  # type: ignore[no-untyped-def]
        return SimpleNamespace(
            orders_unresolved=0,
            stop_reason=None,
            to_jsonable=lambda: {
                "cycle": cycle,
                "orders_submitted": 0,
                "orders_unresolved": 0,
                "instruments_evaluated": 2,
            },
        )


def test_autonomous_cycle_syncs_selects_all_eligible_and_persists_heartbeat(
    tmp_path, monkeypatch
) -> None:  # type: ignore[no-untyped-def]
    from forex_trader.application import autonomous as module

    repository = _FakeRepository()
    engine = SimpleNamespace(
        repository=repository,
        broker=object(),
        fundamentals=SimpleNamespace(),
        fusion_policy=SimpleNamespace(minimum_fundamental_confidence=Decimal("0.5")),
        instrument_universe=lambda: ("EUR_USD", "GBP_USD", "USD_SGD"),
    )
    synchronizer = _FakeSynchronizer()
    now = datetime(2026, 8, 11, 1, tzinfo=UTC)

    monkeypatch.setattr(
        module,
        "select_campaign_universe",
        lambda engine, instruments, **kwargs: CampaignUniverseSelection(
            tuple(instruments),
            ("EUR_USD", "GBP_USD"),
            {"USD_SGD": "missing fundamental state"},
        ),
    )
    monkeypatch.setattr(module, "campaign_policy_context", lambda engine: {"schema": "test"})
    monkeypatch.setattr(module, "PracticeCampaignRunner", _FakeCampaignRunner)

    refresh = FreeOfficialSyncReport(
        started_at=now,
        finished_at=now,
        currencies_attempted=("USD", "EUR"),
        currencies_succeeded=("USD", "EUR"),
        indicators_seen=4,
        observations_inserted=0,
        observations_existing=4,
        raw_payloads_inserted=0,
        components={"policy": 2, "inflation": 2},
        failures={},
    )

    runtime = AutonomousPracticeRuntime(
        _config(tmp_path),
        engine=engine,  # type: ignore[arg-type]
        synchronizer=synchronizer,
        fundamental_sync=lambda database_path: refresh,
        clock=lambda: now,
        monotonic=lambda: 0.0,
        sleeper=lambda seconds: None,
        interval_seconds=0,
    )
    reports = runtime.run(max_cycles=1)

    assert len(reports) == 1
    assert reports[0].discovered_count == 3
    assert reports[0].eligible_count == 2
    assert synchronizer.calls == 2
    assert _FakeCampaignRunner.seen_instruments == ("EUR_USD", "GBP_USD")
    assert repository.states[0]["active"] is True
    assert repository.states[-1]["active"] is False
    assert repository.states[-1]["cycle"] == 1


def test_runtime_lease_is_single_owner() -> None:
    repository = TradingRepository(":memory:")
    assert repository.acquire_runtime_lease(
        "autonomous_practice", "runner-a", ttl_seconds=900
    )
    assert not repository.acquire_runtime_lease(
        "autonomous_practice", "runner-b", ttl_seconds=900
    )
    assert repository.runtime_lease_owner("autonomous_practice") == "runner-a"
    assert repository.renew_runtime_lease(
        "autonomous_practice", "runner-a", ttl_seconds=900
    )
    assert not repository.renew_runtime_lease(
        "autonomous_practice", "runner-b", ttl_seconds=900
    )
    repository.release_runtime_lease("autonomous_practice", "runner-a")
    assert repository.runtime_lease_owner("autonomous_practice") is None
    assert repository.acquire_runtime_lease(
        "autonomous_practice", "runner-b", ttl_seconds=900
    )


def test_autonomous_runtime_refuses_duplicate_runner(tmp_path) -> None:  # type: ignore[no-untyped-def]
    repository = _FakeRepository()
    repository.lease_owner = "existing-runner"
    engine = SimpleNamespace(
        repository=repository,
        broker=object(),
        fundamentals=SimpleNamespace(),
        fusion_policy=SimpleNamespace(minimum_fundamental_confidence=Decimal("0.5")),
        instrument_universe=lambda: ("EUR_USD",),
        runtime_execution_owner=None,
    )
    runtime = AutonomousPracticeRuntime(
        _config(tmp_path),
        engine=engine,  # type: ignore[arg-type]
        synchronizer=_FakeSynchronizer(),
        fundamental_sync=lambda database_path: pytest.fail("refresh must not run"),
        interval_seconds=0,
    )
    with pytest.raises(RuntimeError, match="already owns the durable runner lease"):
        runtime.run(max_cycles=1)
