from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from decimal import Decimal, InvalidOperation
from typing import Protocol

from forex_trader.application.risk_breaker import risk_breaker_resume_cursor


class TransactionSource(Protocol):
    def last_transaction_id(self) -> str: ...

    def transactions_since(self, transaction_id: str) -> tuple[list[dict[str, object]], str]: ...

    def transaction_stream(
        self,
        *,
        max_events: int | None = None,
        include_heartbeats: bool = False,
    ) -> Iterator[dict[str, object]]: ...


class TransactionRepository(Protocol):
    def get_broker_cursor(self, name: str) -> str | None: ...

    def set_broker_cursor(self, name: str, value: str) -> None: ...

    def save_broker_transaction(self, transaction: dict[str, object]) -> bool: ...


class BrokerStateSynchronizer:
    """Maintain an idempotent local transaction ledger and durable OANDA cursor.

    A successful REST catch-up also establishes the durable execution-readiness latch
    when the repository supports it. Practice writes can therefore prove that restart
    recovery/reconciliation happened in this database rather than trusting operator order.

    Realized strategy outcomes are reconstructed from the complete durable broker ledger
    before readiness is granted. Ownership is established from the ``ft-`` client-order
    lineage and the resulting OANDA trade IDs, so capability probes and manual broker
    activity cannot mutate strategy advanced-risk state. Rebuilding the trailing streak
    from owned history also repairs databases contaminated by the pre-v0.7.41 behavior.
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
        """Rebuild the advanced loss streak from strategy-owned closed trades.

        The pre-v0.7.41 implementation incrementally consumed every non-zero
        ``ORDER_FILL.pl``. That allowed capability probes and manual broker activity to
        contaminate the strategy loss streak and made the contaminated value persistent.
        This implementation reconstructs ownership from durable ``ft-`` order lineage,
        derives the exact trailing strategy loss streak, and writes that exact value on
        every reconciliation. A reviewed breaker resume establishes a durable broker
        transaction epoch; outcomes at or before that cursor remain audit history but no
        longer participate in the new consecutive-loss observation window.
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

        outcomes = _strategy_owned_realized_outcomes(transactions)
        context = self._current_risk_context()
        if context is None:
            if any(value != 0 for _, value in outcomes):
                raise RuntimeError("cannot reconcile realized outcomes without a current account snapshot")
            return
        account_id, nav = context

        last_transaction_id: str | None = None
        for transaction in transactions:
            transaction_id = str(transaction.get("id") or "")
            if not transaction_id:
                raise ValueError("durable broker transaction is missing its id")
            transaction_account = str(transaction.get("accountID") or account_id)
            if transaction_account != account_id:
                raise RuntimeError(
                    f"broker transaction {transaction_id} belongs to {transaction_account}, expected {account_id}"
                )
            last_transaction_id = transaction_id

        resume_cursor = risk_breaker_resume_cursor(self.repository, account_id)
        if resume_cursor is not None:
            outcomes = [
                (transaction_id, value)
                for transaction_id, value in outcomes
                if _transaction_id_key(transaction_id) > _transaction_id_key(resume_cursor)
            ]

        loss_streak = 0
        for _transaction_id, realized_pl in outcomes:
            if realized_pl < 0:
                loss_streak += 1
            elif realized_pl > 0:
                loss_streak = 0

        # update_advanced_risk_state has incremental win/loss semantics. Rebuild from
        # zero first, then replay only the trailing owned losses so the persisted state
        # exactly matches durable history and old probe contamination is repaired.
        state_updater(
            account_id=account_id,
            nav=nav,
            realized_loss=False,
            realized_win=True,
        )
        for _ in range(loss_streak):
            state_updater(
                account_id=account_id,
                nav=nav,
                realized_loss=True,
                realized_win=False,
            )

        if last_transaction_id is not None:
            self.repository.set_broker_cursor(self.risk_outcome_cursor_name, last_transaction_id)

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
            reason="broker transaction catch-up and strategy-owned risk reconciliation completed successfully",
        )


def _strategy_owned_realized_outcomes(
    transactions: list[dict[str, object]],
) -> list[tuple[str, Decimal]]:
    """Return realized P/L observations for closed trades opened by ``ft-`` orders."""
    owned_orders: set[str] = set()
    owned_trades: set[str] = set()
    outcomes: list[tuple[str, Decimal]] = []

    for transaction in transactions:
        transaction_id = str(transaction.get("id") or "")
        if not transaction_id:
            raise ValueError("durable broker transaction is missing its id")

        extensions = transaction.get("clientExtensions")
        if isinstance(extensions, dict):
            client_id = str(extensions.get("id") or "")
            tag = str(extensions.get("tag") or "")
            if client_id.startswith("ft-") and tag == "forex-trader":
                owned_orders.add(transaction_id)

        if str(transaction.get("type") or "").upper() != "ORDER_FILL":
            continue

        order_id = str(transaction.get("orderID") or "")
        opened = transaction.get("tradeOpened")
        if order_id in owned_orders and isinstance(opened, dict):
            trade_id = str(opened.get("tradeID") or "")
            if trade_id:
                owned_trades.add(trade_id)

        closed = transaction.get("tradesClosed")
        if not isinstance(closed, list):
            continue
        for trade in closed:
            if not isinstance(trade, dict):
                continue
            trade_id = str(trade.get("tradeID") or "")
            if trade_id not in owned_trades:
                continue
            raw = trade.get("realizedPL")
            if raw is None or not str(raw).strip():
                raw = transaction.get("pl")
            outcomes.append((transaction_id, _parse_realized_pl(raw, transaction_id)))

    return outcomes


def _parse_realized_pl(raw: object, transaction_id: str) -> Decimal:
    if raw is None or not str(raw).strip():
        raise ValueError(f"strategy ORDER_FILL {transaction_id} is missing realized pl")
    try:
        value = Decimal(str(raw))
    except (InvalidOperation, ValueError) as exc:
        raise ValueError(f"strategy ORDER_FILL {transaction_id} has invalid realized pl") from exc
    if not value.is_finite():
        raise ValueError(f"strategy ORDER_FILL {transaction_id} has non-finite realized pl")
    return value


def _realized_fill_pl(transaction: dict[str, object]) -> Decimal | None:
    """Backward-compatible raw fill parser retained for callers/tests outside reconciliation."""
    if str(transaction.get("type") or "").upper() != "ORDER_FILL":
        return None
    raw = transaction.get("pl")
    if raw is None or not str(raw).strip():
        return None
    return _parse_realized_pl(raw, str(transaction.get("id") or "unknown"))


def _transaction_id_key(value: str) -> tuple[int, int | str]:
    stripped = value.strip()
    if not stripped:
        raise ValueError("transaction cursor cannot be empty")
    try:
        return (0, int(stripped))
    except ValueError:
        return (1, stripped)
