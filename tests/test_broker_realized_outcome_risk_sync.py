from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

import pytest

from forex_trader.application.sync import BrokerStateSynchronizer
from forex_trader.domain.models import AccountSnapshot
from forex_trader.infrastructure.advanced_repository import AdvancedTradingRepository

NOW = datetime(2026, 8, 9, 19, 0, tzinfo=UTC)


def fill(transaction_id: str, pl: str, *, account_id: str = "acct") -> dict[str, object]:
    return {
        "id": transaction_id,
        "time": NOW.isoformat(),
        "type": "ORDER_FILL",
        "accountID": account_id,
        "pl": pl,
        "accountBalance": "10000",
    }


class Source:
    account_id = "acct"

    def __init__(self, history: list[dict[str, object]]) -> None:
        self.history = list(history)
        self.pending: list[dict[str, object]] = []

    def account(self) -> AccountSnapshot:
        return AccountSnapshot("acct", "USD", Decimal("10000"), Decimal("10000"))

    def last_transaction_id(self) -> str:
        values = self.history + self.pending
        return str(max((int(str(item["id"])) for item in values), default=0))

    def transactions_between(self, _start: datetime, _end: datetime) -> list[dict[str, object]]:
        return list(self.history)

    def transactions_since(self, transaction_id: str) -> tuple[list[dict[str, object]], str]:
        cursor = int(transaction_id)
        rows = [item for item in self.pending if int(str(item["id"])) > cursor]
        last_id = str(max([cursor, *(int(str(item["id"])) for item in rows)]))
        return rows, last_id

    def transaction_stream(
        self,
        *,
        max_events: int | None = None,
        include_heartbeats: bool = False,
    ):  # type: ignore[no-untyped-def]
        del include_heartbeats
        rows = self.pending if max_events is None else self.pending[:max_events]
        yield from rows


def test_bootstrap_backfills_existing_realized_outcomes_in_transaction_order(tmp_path: Path) -> None:
    repository = AdvancedTradingRepository(tmp_path / "risk-sync.db")
    source = Source(
        [
            fill("1", "0"),
            fill("2", "-5"),
            fill("3", "-3"),
            fill("4", "2"),
            fill("5", "-1"),
        ]
    )
    synchronizer = BrokerStateSynchronizer(source, repository)

    assert synchronizer.catch_up() == 0
    state = repository.advanced_risk_state("acct", Decimal("10000"))
    assert state["loss_streak"] == 1
    assert repository.get_broker_cursor("oanda.transactions.risk-outcomes") == "5"
    assert repository.execution_ready("acct")

    # Re-running reconciliation is idempotent because the dedicated risk cursor
    # has already advanced through transaction 5.
    assert synchronizer.catch_up() == 0
    assert repository.advanced_risk_state("acct", Decimal("10000"))["loss_streak"] == 1


def test_incremental_losses_advance_streak_once_and_win_resets(tmp_path: Path) -> None:
    repository = AdvancedTradingRepository(tmp_path / "risk-incremental.db")
    source = Source([fill("1", "-1")])
    synchronizer = BrokerStateSynchronizer(source, repository)
    synchronizer.catch_up()
    assert repository.advanced_risk_state("acct", Decimal("10000"))["loss_streak"] == 1

    source.pending.extend([fill("2", "-2"), fill("3", "-3")])
    assert synchronizer.catch_up() == 2
    assert repository.advanced_risk_state("acct", Decimal("10000"))["loss_streak"] == 3

    # Same broker transactions cannot count twice.
    assert synchronizer.catch_up() == 0
    assert repository.advanced_risk_state("acct", Decimal("10000"))["loss_streak"] == 3

    source.pending.append(fill("4", "4"))
    assert synchronizer.catch_up() == 1
    assert repository.advanced_risk_state("acct", Decimal("10000"))["loss_streak"] == 0


def test_zero_pl_fill_does_not_reset_or_increment_streak(tmp_path: Path) -> None:
    repository = AdvancedTradingRepository(tmp_path / "risk-breakeven.db")
    source = Source([fill("1", "-1"), fill("2", "0")])
    BrokerStateSynchronizer(source, repository).catch_up()
    assert repository.advanced_risk_state("acct", Decimal("10000"))["loss_streak"] == 1


def test_malformed_realized_pl_blocks_readiness_and_does_not_advance_risk_cursor(tmp_path: Path) -> None:
    repository = AdvancedTradingRepository(tmp_path / "risk-malformed.db")
    source = Source([fill("1", "not-a-number")])
    synchronizer = BrokerStateSynchronizer(source, repository)

    with pytest.raises(ValueError, match="invalid realized pl"):
        synchronizer.catch_up()
    assert repository.get_broker_cursor("oanda.transactions.risk-outcomes") is None
    assert not repository.execution_ready("acct")


def test_cross_account_transaction_blocks_readiness(tmp_path: Path) -> None:
    repository = AdvancedTradingRepository(tmp_path / "risk-account.db")
    source = Source([fill("1", "-1", account_id="other")])

    with pytest.raises(RuntimeError, match="belongs to other"):
        BrokerStateSynchronizer(source, repository).catch_up()
    assert not repository.execution_ready("acct")
