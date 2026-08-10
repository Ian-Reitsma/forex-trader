from __future__ import annotations

import json
import sqlite3
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from statistics import median
from threading import Lock
from uuid import UUID

from forex_trader.domain.costs import CostSample, TradingSession
from forex_trader.domain.macro_history import MacroObservation, MacroObservationKind
from forex_trader.domain.models import DecisionTrace, jsonable
from forex_trader.domain.promotion import PromotionMetrics


class SqliteDecisionRepository:
    def __init__(self, path: str | Path = ":memory:") -> None:
        self.path = str(path)
        self._lock = Lock()
        self._connection = sqlite3.connect(self.path, check_same_thread=False)
        self._connection.row_factory = sqlite3.Row
        self._migrate()

    def _migrate(self) -> None:
        with self._connection:
            self._connection.execute(
                """
                CREATE TABLE IF NOT EXISTS decision_traces (
                    trace_id TEXT PRIMARY KEY,
                    instrument TEXT NOT NULL,
                    disposition TEXT NOT NULL,
                    score TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    created_at TEXT NOT NULL
                )
                """
            )
            self._connection.execute(
                "CREATE INDEX IF NOT EXISTS idx_decisions_created ON decision_traces(created_at DESC)"
            )
            self._connection.execute(
                """
                CREATE TABLE IF NOT EXISTS execution_claims (
                    execution_key TEXT PRIMARY KEY,
                    claimed_at TEXT NOT NULL
                )
                """
            )
            self._connection.execute(
                """
                CREATE TABLE IF NOT EXISTS macro_observations (
                    observation_id TEXT PRIMARY KEY,
                    kind TEXT NOT NULL,
                    currency TEXT NOT NULL,
                    available_at TEXT NOT NULL,
                    payload_json TEXT NOT NULL
                )
                """
            )
            self._connection.execute(
                "CREATE INDEX IF NOT EXISTS idx_macro_available ON macro_observations(available_at, currency)"
            )
            self._connection.execute(
                """
                CREATE TABLE IF NOT EXISTS cost_samples (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    instrument TEXT NOT NULL,
                    observed_at TEXT NOT NULL,
                    session TEXT NOT NULL,
                    spread_pips TEXT NOT NULL,
                    slippage_pips TEXT,
                    event_risk INTEGER NOT NULL DEFAULT 0
                )
                """
            )
            self._connection.execute(
                "CREATE INDEX IF NOT EXISTS idx_cost_session ON cost_samples(instrument, session, observed_at)"
            )
            self._connection.execute(
                """
                CREATE TABLE IF NOT EXISTS broker_transactions (
                    transaction_id TEXT PRIMARY KEY,
                    transaction_type TEXT NOT NULL,
                    transaction_time TEXT,
                    payload_json TEXT NOT NULL
                )
                """
            )
            self._connection.execute(
                "CREATE INDEX IF NOT EXISTS idx_broker_transactions_time ON broker_transactions(transaction_time)"
            )
            self._connection.execute(
                """
                CREATE TABLE IF NOT EXISTS broker_cursors (
                    name TEXT PRIMARY KEY,
                    value TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
                """
            )

    def save_trace(self, trace: DecisionTrace) -> None:
        payload = jsonable(trace)
        with self._lock, self._connection:
            self._connection.execute(
                """
                INSERT OR REPLACE INTO decision_traces
                    (trace_id, instrument, disposition, score, payload_json, created_at)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    str(trace.trace_id),
                    trace.instrument,
                    trace.candidate.disposition.value,
                    str(trace.candidate.score),
                    json.dumps(payload, sort_keys=True),
                    trace.created_at.isoformat(),
                ),
            )

    def recent_traces(self, limit: int = 20) -> list[dict[str, object]]:
        rows = self._connection.execute(
            "SELECT payload_json FROM decision_traces ORDER BY created_at DESC LIMIT ?",
            (max(1, min(limit, 10000)),),
        ).fetchall()
        return [json.loads(row["payload_json"]) for row in rows]

    def claim_execution(self, execution_key: str) -> bool:
        if not execution_key:
            raise ValueError("execution_key is required")
        with self._lock, self._connection:
            cursor = self._connection.execute(
                "INSERT OR IGNORE INTO execution_claims(execution_key, claimed_at) VALUES (?, datetime('now'))",
                (execution_key,),
            )
        return cursor.rowcount == 1

    def release_execution(self, execution_key: str) -> None:
        if not execution_key:
            return
        with self._lock, self._connection:
            self._connection.execute(
                "DELETE FROM execution_claims WHERE execution_key = ?",
                (execution_key,),
            )

    def save_macro_observation(self, observation: MacroObservation) -> None:
        payload = jsonable(observation)
        with self._lock, self._connection:
            self._connection.execute(
                """
                INSERT OR REPLACE INTO macro_observations
                    (observation_id, kind, currency, available_at, payload_json)
                VALUES (?, ?, ?, ?, ?)
                """,
                (
                    str(observation.observation_id),
                    observation.kind.value,
                    observation.currency,
                    observation.available_at.isoformat(),
                    json.dumps(payload, sort_keys=True),
                ),
            )

    def macro_observations(self, *, as_of: datetime | None = None) -> list[MacroObservation]:
        sql = "SELECT payload_json FROM macro_observations"
        params: tuple[object, ...] = ()
        if as_of is not None:
            if as_of.tzinfo is None:
                raise ValueError("as_of must be timezone-aware")
            sql += " WHERE available_at <= ?"
            params = (as_of.isoformat(),)
        sql += " ORDER BY available_at, observation_id"
        rows = self._connection.execute(sql, params).fetchall()
        return [_macro_from_json(json.loads(row["payload_json"])) for row in rows]

    def save_cost_sample(self, sample: CostSample) -> None:
        with self._lock, self._connection:
            self._connection.execute(
                """
                INSERT INTO cost_samples
                    (instrument, observed_at, session, spread_pips, slippage_pips, event_risk)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    sample.instrument,
                    sample.observed_at.isoformat(),
                    sample.session.value,
                    str(sample.spread_pips),
                    str(sample.slippage_pips) if sample.slippage_pips is not None else None,
                    1 if sample.event_risk else 0,
                ),
            )

    def cost_samples(self, *, limit: int = 10000) -> list[CostSample]:
        rows = self._connection.execute(
            """
            SELECT instrument, observed_at, session, spread_pips, slippage_pips, event_risk
            FROM cost_samples ORDER BY observed_at DESC LIMIT ?
            """,
            (max(1, min(limit, 100000)),),
        ).fetchall()
        return [
            CostSample(
                instrument=row["instrument"],
                observed_at=datetime.fromisoformat(row["observed_at"]),
                session=TradingSession(row["session"]),
                spread_pips=Decimal(row["spread_pips"]),
                slippage_pips=(
                    Decimal(row["slippage_pips"]) if row["slippage_pips"] is not None else None
                ),
                event_risk=bool(row["event_risk"]),
            )
            for row in reversed(rows)
        ]

    def save_broker_transaction(self, transaction: dict[str, object]) -> bool:
        transaction_id = str(transaction.get("id") or "")
        if not transaction_id:
            raise ValueError("broker transaction id is required")
        transaction_type = str(transaction.get("type") or "UNKNOWN")
        transaction_time = str(transaction.get("time") or "") or None
        with self._lock, self._connection:
            cursor = self._connection.execute(
                """
                INSERT OR IGNORE INTO broker_transactions
                    (transaction_id, transaction_type, transaction_time, payload_json)
                VALUES (?, ?, ?, ?)
                """,
                (
                    transaction_id,
                    transaction_type,
                    transaction_time,
                    json.dumps(transaction, sort_keys=True),
                ),
            )
        return cursor.rowcount == 1

    def broker_transactions(self, *, limit: int = 10000) -> list[dict[str, object]]:
        rows = self._connection.execute(
            """
            SELECT payload_json FROM broker_transactions
            ORDER BY CAST(transaction_id AS INTEGER), transaction_id LIMIT ?
            """,
            (max(1, min(limit, 100000)),),
        ).fetchall()
        return [json.loads(row["payload_json"]) for row in rows]

    def set_broker_cursor(self, name: str, value: str) -> None:
        if not name or not value:
            raise ValueError("cursor name and value are required")
        with self._lock, self._connection:
            self._connection.execute(
                """
                INSERT INTO broker_cursors(name, value, updated_at)
                VALUES (?, ?, datetime('now'))
                ON CONFLICT(name) DO UPDATE SET value=excluded.value, updated_at=excluded.updated_at
                """,
                (name, value),
            )

    def get_broker_cursor(self, name: str) -> str | None:
        row = self._connection.execute(
            "SELECT value FROM broker_cursors WHERE name = ?", (name,)
        ).fetchone()
        return None if row is None else str(row["value"])

    def promotion_metrics(self) -> PromotionMetrics:
        traces = self.recent_traces(10000)
        decisions = len(traces)
        trade_candidates = sum(
            1 for trace in traces if trace.get("candidate", {}).get("disposition") == "trade"
        )
        submitted_orders = 0
        rejected_orders = 0
        unknown_orders = 0
        for trace in traces:
            order = trace.get("order")
            if not isinstance(order, dict):
                continue
            submitted_orders += 1
            if order.get("status") == "rejected":
                rejected_orders += 1
            elif order.get("status") == "unknown":
                unknown_orders += 1

        transactions = self.broker_transactions(limit=100000)
        our_orders: set[str] = set()
        our_trades: set[str] = set()
        closed_values: list[Decimal] = []
        for transaction in transactions:
            extensions = transaction.get("clientExtensions")
            if isinstance(extensions, dict):
                client_id = str(extensions.get("id") or "")
                tag = str(extensions.get("tag") or "")
                if client_id.startswith("ft-") or tag == "forex-trader":
                    tx_id = str(transaction.get("id") or "")
                    if tx_id:
                        our_orders.add(tx_id)
            if transaction.get("type") == "ORDER_FILL":
                order_id = str(transaction.get("orderID") or "")
                opened = transaction.get("tradeOpened")
                if order_id in our_orders and isinstance(opened, dict):
                    trade_id = str(opened.get("tradeID") or "")
                    if trade_id:
                        our_trades.add(trade_id)
                closed = transaction.get("tradesClosed")
                if isinstance(closed, list):
                    for trade in closed:
                        if not isinstance(trade, dict):
                            continue
                        if str(trade.get("tradeID") or "") not in our_trades:
                            continue
                        value = Decimal(str(trade.get("realizedPL", transaction.get("pl", "0"))))
                        value += Decimal(str(trade.get("financing", "0")))
                        closed_values.append(value)

        gross_profit = sum((value for value in closed_values if value > 0), Decimal("0"))
        gross_loss = -sum((value for value in closed_values if value < 0), Decimal("0"))
        total_pl = sum(closed_values, Decimal("0"))
        equity = Decimal("0")
        peak = Decimal("0")
        max_drawdown = Decimal("0")
        for value in closed_values:
            equity += value
            peak = max(peak, equity)
            max_drawdown = max(max_drawdown, peak - equity)

        slippages = [
            sample.slippage_pips
            for sample in self.cost_samples(limit=100000)
            if sample.slippage_pips is not None
        ]
        median_slippage = (
            Decimal(str(median(slippages))) if slippages else None
        )
        return PromotionMetrics(
            decisions=decisions,
            trade_candidates=trade_candidates,
            submitted_orders=submitted_orders,
            rejected_orders=rejected_orders,
            unknown_orders=unknown_orders,
            closed_trades=len(closed_values),
            wins=sum(value > 0 for value in closed_values),
            total_pl=total_pl,
            gross_profit=gross_profit,
            gross_loss=gross_loss,
            max_drawdown=max_drawdown,
            median_slippage_pips=median_slippage,
        )

    def close(self) -> None:
        self._connection.close()

    def __enter__(self) -> "SqliteDecisionRepository":
        return self

    def __exit__(self, exc_type: object, exc: object, traceback: object) -> None:
        self.close()

    def __del__(self) -> None:
        try:
            self._connection.close()
        except Exception:
            pass


def _macro_from_json(payload: dict[str, object]) -> MacroObservation:
    return MacroObservation(
        observation_id=UUID(str(payload["observation_id"])),
        kind=MacroObservationKind(str(payload["kind"])),
        currency=str(payload["currency"]),
        available_at=datetime.fromisoformat(str(payload["available_at"])),
        source=str(payload.get("source", "manual")),
        category=str(payload.get("category", "")),
        actual=(Decimal(str(payload["actual"])) if payload.get("actual") is not None else None),
        forecast=(Decimal(str(payload["forecast"])) if payload.get("forecast") is not None else None),
        previous=(Decimal(str(payload["previous"])) if payload.get("previous") is not None else None),
        higher_is_positive=bool(payload.get("higher_is_positive", True)),
        importance=Decimal(str(payload.get("importance", "1"))),
        headline=str(payload.get("headline", "")),
        body=str(payload.get("body", "")),
        source_weight=Decimal(str(payload.get("source_weight", "0.7"))),
        revision_of=(UUID(str(payload["revision_of"])) if payload.get("revision_of") else None),
        event_at=(datetime.fromisoformat(str(payload["event_at"])) if payload.get("event_at") else None),
    )
