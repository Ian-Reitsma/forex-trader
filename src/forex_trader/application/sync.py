from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal, InvalidOperation
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

    Realized ORDER_FILL outcomes are replayed from the durable transaction ledger into
    advanced risk state before readiness is granted. A second durable cursor makes this
    idempotent and also backfills databases that already contained broker transactions
    before loss-streak observation was wired into synchronization.
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
        self.risk_outcome_cursor_name = f"{cursor_name}.risk-outcomes"
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
            self._backfill_history(history, start=start, end=now)
        self.repository.set_broker_cursor(self.cursor_name, cursor)
        return cursor

    def _backfill_history(self, history, *, start: datetime, end: datetime) -> None:  # type: ignore[no-untyped-def]
        """Backfill bounded transaction windows while tolerating pre-account ranges.

        OANDA limits time-based transaction requests to one year. When a requested
        starting timestamp predates account creation, OANDA substitutes the account
        creation time; windows ending before account creation then become an invalid
        range and return HTTP 416. Leading 416 windows are therefore skipped until the
        first valid account-history window is reached. After one valid window has been
        observed, any later 416 is treated as a real reconciliation failure and raised.
        """
        cursor = start.astimezone(UTC)
        final = end.astimezone(UTC)
        valid_window_seen = False
        while cursor < final:
            window_end = min(final, cursor + timedelta(days=364))
            try:
                transactions = history(cursor, window_end)
            except RuntimeError as exc:
                if (
                    getattr(exc, "status_code", None) == 416
                    and not valid_window_seen
                    and window_end < final
                ):
                    cursor = window_end
                    continue
                raise
            valid_window_seen = True
            for transaction in transactions:
                if isinstance(transaction, dict) and transaction.get("id"):
                    self.repository.save_broker_transaction(transaction)
            cursor = window_end

    def catch_up(self) -> int:
        cursor = self.bootstrap()
        transactions, last_id = self.source.transactions_since(cursor)
        inserted = 0
        for transaction in transactions:
            if self.repository.save_broker_transaction(transaction):
                inserted += 1
        self.repository.set_broker_cursor(self.cursor_name, last_id)
        self._reconcile_realized_outcomes()
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

    def _reconcile_realized_outcomes(self) -> None:
        """Advance the durable loss-streak observation cursor from saved fills.

        OANDA ORDER_FILL transactions expose ``pl`` in account currency. Zero-PL
        fills do not alter a consecutive win/loss streak. Positive realized P/L resets
        the streak and negative realized P/L increments it. The update is applied only
        after the broker transaction itself is durable, and the risk cursor advances
        only after each transaction has been interpreted successfully.
        """
        transactions_reader = getattr(self.repository, "broker_transactions", None)
        state_updater = getattr(self.repository, "update_advanced_risk_state", None)
        if transactions_reader is None or state_updater is None:
            return
        transactions = transactions_reader(limit=100000)
        if not isinstance(transactions, list):
            raise RuntimeError("broker_transactions must return a list for risk-state reconciliation")
        if len(transactions) >= 100000:
            raise RuntimeError("risk-state reconciliation requires pagination beyond 100000 broker transactions")

        context = self._current_risk_context()
        if context is None:
            # Reconciliation must not invent NAV or account identity. A source without
            # an account snapshot simply cannot establish advanced-risk parity/readiness.
            if any(_realized_fill_pl(item) not in {None, Decimal("0")} for item in transactions):
                raise RuntimeError("cannot reconcile realized outcomes without a current account snapshot")
            return
        account_id, nav = context
        risk_cursor = self.repository.get_broker_cursor(self.risk_outcome_cursor_name)
        for transaction in transactions:
            transaction_id = str(transaction.get("id") or "")
            if not transaction_id:
                raise ValueError("durable broker transaction is missing its id")
            if risk_cursor is not None and _transaction_id_key(transaction_id) <= _transaction_id_key(risk_cursor):
                continue
            transaction_account = str(transaction.get("accountID") or account_id)
            if transaction_account != account_id:
                raise RuntimeError(
                    f"broker transaction {transaction_id} belongs to {transaction_account}, expected {account_id}"
                )
            realized_pl = _realized_fill_pl(transaction)
            if realized_pl is not None and realized_pl != 0:
                state_updater(
                    account_id=account_id,
                    nav=nav,
                    realized_loss=realized_pl < 0,
                    realized_win=realized_pl > 0,
                )
            self.repository.set_broker_cursor(self.risk_outcome_cursor_name, transaction_id)
            risk_cursor = transaction_id

    def _current_risk_context(self) -> tuple[str, Decimal] | None:
        account_reader = getattr(self.source, "account", None)
        if account_reader is None:
            return None
        try:
            account = account_reader()
        except (AttributeError, RuntimeError, ValueError):
            return None
        account_id = str(getattr(account, "account_id", "") or "")
        try:
            nav = Decimal(str(getattr(account, "nav")))
        except (AttributeError, InvalidOperation, ValueError):
            return None
        if not account_id or not nav.is_finite() or nav <= 0:
            return None
        return account_id, nav

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
            reason="broker transaction catch-up and realized-outcome risk reconciliation completed successfully",
        )


def _realized_fill_pl(transaction: dict[str, object]) -> Decimal | None:
    if str(transaction.get("type") or "").upper() != "ORDER_FILL":
        return None
    raw = transaction.get("pl")
    if raw is None or not str(raw).strip():
        return None
    try:
        value = Decimal(str(raw))
    except (InvalidOperation, ValueError) as exc:
        raise ValueError(f"ORDER_FILL {transaction.get('id')} has invalid realized pl") from exc
    if not value.is_finite():
        raise ValueError(f"ORDER_FILL {transaction.get('id')} has non-finite realized pl")
    return value


def _transaction_id_key(value: str) -> tuple[int, int | str]:
    stripped = value.strip()
    if not stripped:
        raise ValueError("transaction cursor cannot be empty")
    try:
        return (0, int(stripped))
    except ValueError:
        return (1, stripped)
