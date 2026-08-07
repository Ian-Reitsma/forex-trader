from __future__ import annotations

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
    """Maintains an idempotent local transaction ledger and durable OANDA cursor."""

    def __init__(
        self,
        source: TransactionSource,
        repository: TransactionRepository,
        *,
        cursor_name: str = "oanda.transactions",
    ) -> None:
        self.source = source
        self.repository = repository
        self.cursor_name = cursor_name

    def bootstrap(self) -> str:
        cursor = self.repository.get_broker_cursor(self.cursor_name)
        if cursor is not None:
            return cursor
        cursor = self.source.last_transaction_id()
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
        return inserted

    def stream(self, *, max_events: int | None = None) -> int:
        self.catch_up()
        inserted = 0
        for payload in self.source.transaction_stream(
            max_events=max_events,
            include_heartbeats=True,
        ):
            kind = str(payload.get("type") or "")
            if kind == "HEARTBEAT":
                last_id = str(payload.get("lastTransactionID") or "")
                if last_id:
                    self.repository.set_broker_cursor(self.cursor_name, last_id)
                continue
            transaction_id = str(payload.get("id") or "")
            if transaction_id and self.repository.save_broker_transaction(payload):
                inserted += 1
            if transaction_id:
                self.repository.set_broker_cursor(self.cursor_name, transaction_id)
        return inserted
