from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

import pytest

from forex_trader.application.risk_breaker import review_loss_streak_breaker
from forex_trader.application.sync import BrokerStateSynchronizer
from forex_trader.domain.models import AccountSnapshot
from forex_trader.infrastructure.advanced_repository import AdvancedTradingRepository

NOW = datetime(2026, 8, 9, 19, 0, tzinfo=UTC)


def market_order(
    transaction_id: str,
    *,
    client_id: str = "ft-strategy-order",
    tag: str = "forex-trader",
    account_id: str = "acct",
) -> dict[str, object]:
    return {
        "id": transaction_id,
        "time": NOW.isoformat(),
        "type": "MARKET_ORDER",
        "accountID": account_id,
        "clientExtensions": {"id": client_id, "tag": tag},
    }


def open_fill(
    transaction_id: str,
    order_id: str,
    trade_id: str,
    *,
    account_id: str = "acct",
) -> dict[str, object]:
    return {
        "id": transaction_id,
        "time": NOW.isoformat(),
        "type": "ORDER_FILL",
        "accountID": account_id,
        "orderID": order_id,
        "pl": "0",
        "tradeOpened": {"tradeID": trade_id},
    }


def close_fill(
    transaction_id: str,
    trade_id: str,
    pl: str,
    *,
    account_id: str = "acct",
) -> dict[str, object]:
    return {
        "id": transaction_id,
        "time": NOW.isoformat(),
        "type": "ORDER_FILL",
        "accountID": account_id,
        "orderID": f"dependent-{transaction_id}",
        "pl": pl,
        "tradesClosed": [{"tradeID": trade_id, "realizedPL": pl, "financing": "0"}],
    }


def strategy_trade(
    order_id: int,
    pl: str,
    *,
    client_id: str | None = None,
    account_id: str = "acct",
) -> list[dict[str, object]]:
    order = str(order_id)
    opened = str(order_id + 1)
    closed = str(order_id + 2)
    trade_id = f"trade-{opened}"
    return [
        market_order(
            order,
            client_id=client_id or f"ft-strategy-{order}",
            account_id=account_id,
        ),
        open_fill(opened, order, trade_id, account_id=account_id),
        close_fill(closed, trade_id, pl, account_id=account_id),
    ]


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


def test_bootstrap_rebuilds_trailing_strategy_loss_streak_in_transaction_order(tmp_path: Path) -> None:
    repository = AdvancedTradingRepository(tmp_path / "risk-sync.db")
    source = Source(
        [
            *strategy_trade(1, "-5"),
            *strategy_trade(4, "-3"),
            *strategy_trade(7, "2"),
            *strategy_trade(10, "-1"),
        ]
    )
    synchronizer = BrokerStateSynchronizer(source, repository)

    assert synchronizer.catch_up() == 0
    state = repository.advanced_risk_state("acct", Decimal("10000"))
    assert state["loss_streak"] == 1
    assert repository.get_broker_cursor("oanda.transactions.risk-outcomes") == "12"
    assert repository.execution_ready("acct")

    assert synchronizer.catch_up() == 0
    assert repository.advanced_risk_state("acct", Decimal("10000"))["loss_streak"] == 1


def test_probe_and_manual_losses_do_not_contaminate_strategy_streak(tmp_path: Path) -> None:
    repository = AdvancedTradingRepository(tmp_path / "risk-ownership.db")
    probe = strategy_trade(1, "-0.0002", client_id="probe-capability")
    manual = [
        market_order("4", client_id="manual-order", tag="manual"),
        open_fill("5", "4", "manual-trade"),
        close_fill("6", "manual-trade", "-50"),
    ]
    source = Source([*probe, *manual, *strategy_trade(7, "-10")])

    BrokerStateSynchronizer(source, repository).catch_up()
    assert repository.advanced_risk_state("acct", Decimal("10000"))["loss_streak"] == 1


def test_probe_win_does_not_reset_strategy_loss_streak(tmp_path: Path) -> None:
    repository = AdvancedTradingRepository(tmp_path / "risk-probe-win.db")
    source = Source(
        [
            *strategy_trade(1, "-10"),
            *strategy_trade(4, "5", client_id="probe-capability"),
        ]
    )

    BrokerStateSynchronizer(source, repository).catch_up()
    assert repository.advanced_risk_state("acct", Decimal("10000"))["loss_streak"] == 1


def test_incremental_owned_losses_advance_once_and_owned_win_resets(tmp_path: Path) -> None:
    repository = AdvancedTradingRepository(tmp_path / "risk-incremental.db")
    source = Source(strategy_trade(1, "-1"))
    synchronizer = BrokerStateSynchronizer(source, repository)
    synchronizer.catch_up()
    assert repository.advanced_risk_state("acct", Decimal("10000"))["loss_streak"] == 1

    source.pending.extend([*strategy_trade(4, "-2"), *strategy_trade(7, "-3")])
    assert synchronizer.catch_up() == 6
    assert repository.advanced_risk_state("acct", Decimal("10000"))["loss_streak"] == 3

    assert synchronizer.catch_up() == 0
    assert repository.advanced_risk_state("acct", Decimal("10000"))["loss_streak"] == 3

    source.pending.extend(strategy_trade(10, "4"))
    assert synchronizer.catch_up() == 3
    assert repository.advanced_risk_state("acct", Decimal("10000"))["loss_streak"] == 0


def test_zero_pl_owned_close_does_not_reset_or_increment_streak(tmp_path: Path) -> None:
    repository = AdvancedTradingRepository(tmp_path / "risk-breakeven.db")
    source = Source([*strategy_trade(1, "-1"), *strategy_trade(4, "0")])
    BrokerStateSynchronizer(source, repository).catch_up()
    assert repository.advanced_risk_state("acct", Decimal("10000"))["loss_streak"] == 1


def test_daily_financing_does_not_create_an_independent_streak_observation(tmp_path: Path) -> None:
    repository = AdvancedTradingRepository(tmp_path / "risk-financing.db")
    rows = strategy_trade(1, "-1")
    rows.insert(
        2,
        {
            "id": "3",
            "time": NOW.isoformat(),
            "type": "DAILY_FINANCING",
            "accountID": "acct",
            "financing": "-2.5",
            "positionFinancings": [],
        },
    )
    rows[-1]["id"] = "4"
    source = Source(rows)

    BrokerStateSynchronizer(source, repository).catch_up()
    assert repository.advanced_risk_state("acct", Decimal("10000"))["loss_streak"] == 1


def test_reviewed_breaker_resume_establishes_new_durable_loss_epoch(tmp_path: Path) -> None:
    repository = AdvancedTradingRepository(tmp_path / "risk-review.db")
    history: list[dict[str, object]] = []
    for order_id in range(1, 19, 3):
        history.extend(strategy_trade(order_id, "-1"))
    source = Source(history)
    synchronizer = BrokerStateSynchronizer(source, repository)
    synchronizer.catch_up()
    assert repository.advanced_risk_state("acct", Decimal("10000"))["loss_streak"] == 6

    review_loss_streak_breaker(
        repository,
        account_id="acct",
        nav=Decimal("10000"),
        max_loss_streak=6,
        broker_cursor="18",
        review_id="review-20260812",
        reason="operator reviewed six owned Practice strategy losses",
        reviewed_at=NOW,
    )
    synchronizer.catch_up()
    assert repository.advanced_risk_state("acct", Decimal("10000"))["loss_streak"] == 0

    source.pending.extend(strategy_trade(19, "-2"))
    assert synchronizer.catch_up() == 3
    assert repository.advanced_risk_state("acct", Decimal("10000"))["loss_streak"] == 1

    restarted = BrokerStateSynchronizer(source, repository)
    assert restarted.catch_up() == 0
    assert repository.advanced_risk_state("acct", Decimal("10000"))["loss_streak"] == 1


def test_malformed_owned_realized_pl_blocks_readiness_and_does_not_advance_risk_cursor(tmp_path: Path) -> None:
    repository = AdvancedTradingRepository(tmp_path / "risk-malformed.db")
    source = Source(strategy_trade(1, "not-a-number"))
    synchronizer = BrokerStateSynchronizer(source, repository)

    with pytest.raises(ValueError, match="invalid realized pl"):
        synchronizer.catch_up()
    assert repository.get_broker_cursor("oanda.transactions.risk-outcomes") is None
    assert not repository.execution_ready("acct")


def test_malformed_unowned_fill_does_not_block_strategy_reconciliation(tmp_path: Path) -> None:
    repository = AdvancedTradingRepository(tmp_path / "risk-unowned-malformed.db")
    source = Source(
        [
            {
                "id": "1",
                "time": NOW.isoformat(),
                "type": "ORDER_FILL",
                "accountID": "acct",
                "pl": "not-a-number",
            }
        ]
    )

    BrokerStateSynchronizer(source, repository).catch_up()
    assert repository.advanced_risk_state("acct", Decimal("10000"))["loss_streak"] == 0
    assert repository.execution_ready("acct")


def test_cross_account_transaction_blocks_readiness(tmp_path: Path) -> None:
    repository = AdvancedTradingRepository(tmp_path / "risk-account.db")
    source = Source([market_order("1", account_id="other")])

    with pytest.raises(RuntimeError, match="belongs to other"):
        BrokerStateSynchronizer(source, repository).catch_up()
    assert not repository.execution_ready("acct")
