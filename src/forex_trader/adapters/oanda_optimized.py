from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from decimal import Decimal
from typing import Any

from forex_trader.adapters.oanda_safe import SafeOandaPracticeClient
from forex_trader.domain.models import AccountSnapshot, OpenPosition


class OptimizedOandaPracticeClient(SafeOandaPracticeClient):
    """Hardened Practice client with coherent account/position risk snapshots.

    OANDA's account-details response contains both account summary fields and positions.
    During an explicit `risk_read_scope`, `account_summary()` therefore fetches one fresh
    account-details payload and stores only its parsed position list for the immediately
    following `positions()` read in the same context. The positions snapshot is one-shot.

    The next account-summary call always reaches OANDA again, so the engine's initial risk
    checkpoint and pre-send checkpoint remain independent fresh snapshots. Outside the
    scope, inherited `/summary` and `/openPositions` behavior remains unchanged.
    """

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self._risk_scope_active: ContextVar[bool] = ContextVar(
            f"forex_trader_oanda_risk_scope_{id(self)}",
            default=False,
        )
        self._pending_positions: ContextVar[list[OpenPosition] | None] = ContextVar(
            f"forex_trader_oanda_positions_{id(self)}",
            default=None,
        )

    @contextmanager
    def risk_read_scope(self) -> Iterator[None]:
        """Enable one-shot account-details -> positions reuse for one engine decision."""
        if self._risk_scope_active.get():
            yield
            return
        active_token = self._risk_scope_active.set(True)
        positions_token = self._pending_positions.set(None)
        try:
            yield
        finally:
            self._pending_positions.reset(positions_token)
            self._risk_scope_active.reset(active_token)

    def account_summary(self) -> AccountSnapshot:
        if not self._risk_scope_active.get():
            return super().account_summary()
        payload = self._request("GET", f"/v3/accounts/{self._account_id()}")
        account = payload.get("account")
        if not isinstance(account, dict):
            raise ValueError("OANDA account-details response did not contain an account object")
        self._pending_positions.set(_open_positions_from_account(account))
        return _account_snapshot_from_account(account, realized_pl_today=self.realized_pl_today())

    def positions(self) -> list[OpenPosition]:
        if self._risk_scope_active.get():
            pending = self._pending_positions.get()
            if pending is not None:
                # One-shot consumption prevents an unrelated later positions() call from
                # silently reusing an older account-details response.
                self._pending_positions.set(None)
                return list(pending)
        return super().positions()


def _account_snapshot_from_account(
    account: dict[str, Any],
    *,
    realized_pl_today: Decimal,
) -> AccountSnapshot:
    return AccountSnapshot(
        account_id=str(account["id"]),
        currency=str(account["currency"]),
        balance=Decimal(str(account["balance"])),
        nav=Decimal(str(account["NAV"])),
        margin_used=Decimal(str(account.get("marginUsed", "0"))),
        margin_available=Decimal(str(account.get("marginAvailable", "0"))),
        unrealized_pl=Decimal(str(account.get("unrealizedPL", "0"))),
        open_position_count=int(account.get("openPositionCount", 0)),
        realized_pl_today=realized_pl_today,
    )


def _open_positions_from_account(account: dict[str, Any]) -> list[OpenPosition]:
    positions: list[OpenPosition] = []
    raw_positions = account.get("positions", [])
    if not isinstance(raw_positions, list):
        raise ValueError("OANDA account-details positions must be a list")
    for item in raw_positions:
        if not isinstance(item, dict):
            continue
        long = item.get("long", {})
        short = item.get("short", {})
        if not isinstance(long, dict):
            long = {}
        if not isinstance(short, dict):
            short = {}
        long_units = Decimal(str(long.get("units", "0")))
        short_units = Decimal(str(short.get("units", "0")))
        if long_units + short_units == 0:
            continue
        positions.append(
            OpenPosition(
                instrument=str(item.get("instrument", "")).upper(),
                long_units=long_units,
                short_units=short_units,
                long_average_price=(
                    Decimal(str(long["averagePrice"]))
                    if long.get("averagePrice") is not None
                    else None
                ),
                short_average_price=(
                    Decimal(str(short["averagePrice"]))
                    if short.get("averagePrice") is not None
                    else None
                ),
                unrealized_pl=Decimal(str(item.get("unrealizedPL", "0"))),
            )
        )
    return positions
