from __future__ import annotations

from decimal import Decimal

import pytest

from forex_trader.application.sync import BrokerStateSynchronizer
from forex_trader.infrastructure.advanced_repository import AdvancedTradingRepository


class MinimalRepository:
    def get_broker_cursor(self, _name: str) -> str | None:
        return None

    def set_broker_cursor(self, _name: str, _value: str) -> None:
        return None

    def save_broker_transaction(self, _transaction: dict[str, object]) -> bool:
        return True


class NonListRiskRepository(MinimalRepository):
    def broker_transactions(self, *, limit: int = 1000) -> tuple[dict[str, object], ...]:
        del limit
        return ()

    def update_advanced_risk_state(self, **_kwargs: object) -> None:
        return None


class HugeList(list[dict[str, object]]):
    def __len__(self) -> int:
        return 100000


class HugeRiskRepository(MinimalRepository):
    def broker_transactions(self, *, limit: int = 1000) -> list[dict[str, object]]:
        del limit
        return HugeList()

    def update_advanced_risk_state(self, **_kwargs: object) -> None:
        return None


def test_reconciliation_rejects_non_list_and_unbounded_transaction_snapshots() -> None:
    synchronizer = BrokerStateSynchronizer(object(), NonListRiskRepository())  # type: ignore[arg-type]
    with pytest.raises(RuntimeError, match="must return a list"):
        synchronizer._reconcile_realized_outcomes()

    synchronizer = BrokerStateSynchronizer(object(), HugeRiskRepository())  # type: ignore[arg-type]
    with pytest.raises(RuntimeError, match="requires pagination"):
        synchronizer._reconcile_realized_outcomes()


def _owned_loss_rows() -> list[dict[str, object]]:
    return [
        {
            "id": "1",
            "type": "MARKET_ORDER",
            "clientExtensions": {"id": "ft-owned", "tag": "forex-trader"},
        },
        {
            "id": "2",
            "type": "ORDER_FILL",
            "orderID": "1",
            "tradeOpened": {"tradeID": "trade-1"},
            "pl": "0",
        },
        {
            "id": "3",
            "type": "ORDER_FILL",
            "pl": "-1",
            "tradesClosed": [{"tradeID": "trade-1", "realizedPL": "-1"}],
        },
    ]


def test_owned_outcomes_fail_closed_when_account_context_is_unavailable() -> None:
    repository = AdvancedTradingRepository(":memory:")
    for row in _owned_loss_rows():
        repository.save_broker_transaction(row)
    synchronizer = BrokerStateSynchronizer(object(), repository)  # type: ignore[arg-type]
    with pytest.raises(RuntimeError, match="without a current account snapshot"):
        synchronizer._reconcile_realized_outcomes()


def test_empty_outcome_history_tolerates_missing_or_invalid_account_context() -> None:
    repository = AdvancedTradingRepository(":memory:")
    repository.save_broker_transaction({"id": "1", "type": "CREATE"})

    class RaisingAccount:
        def account(self) -> object:
            raise RuntimeError("unavailable")

    BrokerStateSynchronizer(RaisingAccount(), repository)._reconcile_realized_outcomes()  # type: ignore[arg-type]

    class InvalidNavAccount:
        def account(self) -> object:
            return type("Account", (), {"account_id": "acct", "nav": "not-a-number"})()

    BrokerStateSynchronizer(InvalidNavAccount(), repository)._reconcile_realized_outcomes()  # type: ignore[arg-type]

    class BlankAccount:
        def account(self) -> object:
            return type("Account", (), {"account_id": "", "nav": Decimal("0")})()

    BrokerStateSynchronizer(BlankAccount(), repository)._reconcile_realized_outcomes()  # type: ignore[arg-type]


def test_synchronizer_constructor_and_readiness_account_resolution_edges() -> None:
    with pytest.raises(ValueError, match="initial_history_days"):
        BrokerStateSynchronizer(object(), MinimalRepository(), initial_history_days=0)  # type: ignore[arg-type]

    calls: list[tuple[str, bool, str, str]] = []

    class ReadinessRepository(MinimalRepository):
        def set_execution_readiness(
            self,
            account_id: str,
            ready: bool,
            *,
            broker_cursor: str,
            reason: str,
        ) -> None:
            calls.append((account_id, ready, broker_cursor, reason))

    class CallableAccountIdSource:
        def account_id(self) -> str:
            return "callable-account"

    sync = BrokerStateSynchronizer(CallableAccountIdSource(), ReadinessRepository())  # type: ignore[arg-type]
    sync._mark_execution_ready("55")
    assert calls[-1][:3] == ("callable-account", True, "55")

    class AccountFallbackSource:
        def account(self) -> object:
            return type("Account", (), {"account_id": "fallback-account"})()

    sync = BrokerStateSynchronizer(AccountFallbackSource(), ReadinessRepository())  # type: ignore[arg-type]
    sync._mark_execution_ready("56")
    assert calls[-1][:3] == ("fallback-account", True, "56")

    class MissingAccountSource:
        def account(self) -> object:
            raise ValueError("missing")

    previous_count = len(calls)
    sync = BrokerStateSynchronizer(MissingAccountSource(), ReadinessRepository())  # type: ignore[arg-type]
    sync._mark_execution_ready("57")
    assert len(calls) == previous_count
