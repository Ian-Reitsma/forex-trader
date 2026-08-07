from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Protocol


class TransactionSource(Protocol):
    def last_transaction_id(self) -> str: ...

    def transactions_since(self, transaction_id: str) -> tuple[list[dict[str, object]], str]: ...

    def transaction_stream(
        self,
        *,
        max_events: int | None = None,
        include_heartbeats: bool = False,
    ): ...


class TransactionRepository(Protocol):
    def get_broker_cursor(self, name: str) -> str | None: ...

    def set_broker_cursor(self, name: str, value: str) -> None: ...

    def save_broker_transaction(self, transaction: dict[str, object]) -> bool: ...


class BrokerStateSynchronizer:
    """Maintain an idempotent local transaction ledger and durable OANDA cursor.

    A successful REST catch-up also establishes the durable execution-readiness latch
    when the repository supports it. Practice writes can therefore prove that restart
    recovery/reconciliation happened in this database rather than trusting operator order.
    """

    def __init__(
        self,
        source: TransactionSource,
        repository: TransactionRepository,
        *,
        cursor_name: str = "oanda.transactions",
        initial_history_days: int = 3650,
    ) -> None:
        if initial_history_days < 1:
            raise ValueError("initial_history_days must be positive")
        self.source = source
        self.repository = repository
        self.cursor_name = cursor_name
        self.initial_history_days = initial_history_days

    def bootstrap(self) -> str:
        cursor = self.repository.get_broker_cursor(self.cursor_name)
        if cursor is not None:
            return cursor
        cursor = self.source.last_transaction_id()
        history = getattr(self.source, "transactions_between", None)
        if history is not None:
            now = datetime.now(UTC)
            start = now - timedelta(days=self.initial_history_days)
            for transaction in history(start, now + timedelta(seconds=1)):
                if isinstance(transaction, dict) and transaction.get("id"):
                    self.repository.save_broker_transaction(transaction)
        self.repository.set_broker_cursor(self.cursor_name, cursor)
        return cursor

    def catch_up(self) -> int:
        cursor = self.bootstrap()
        transactions, last_id = self.source.transactions_since(cursor)
        inserted = 0
        for transaction in transactions:
            if self.repository.save_broker_transaction(transaction):
                inserted += 1
        self.repository.set_broker_cursor(self.cursor_name, last_id)
        self._mark_execution_ready(last_id)
        return inserted

    def stream(self, *, max_events: int | None = None) -> int:
        self.catch_up()
        inserted = 0
        for payload in self.source.transaction_stream(max_events=max_events, include_heartbeats=True):
            kind = str(payload.get("type") or "")
            if kind == "HEARTBEAT":
                self.catch_up()
                continue
            transaction_id = str(payload.get("id") or "")
            if transaction_id and self.repository.save_broker_transaction(payload):
                inserted += 1
            if transaction_id:
                self.repository.set_broker_cursor(self.cursor_name, transaction_id)
        self.catch_up()
        return inserted

    def _mark_execution_ready(self, cursor: str) -> None:
        setter = getattr(self.repository, "set_execution_readiness", None)
        if setter is None:
            return
        account_id = getattr(self.source, "account_id", None)
        if callable(account_id):
            account_id = account_id()
        if not account_id:
            try:
                account_id = self.source.account().account_id  # type: ignore[attr-defined]
            except (AttributeError, RuntimeError, ValueError):
                return
        setter(
            str(account_id),
            True,
            broker_cursor=cursor,
            reason="broker transaction catch-up completed successfully",
        )
