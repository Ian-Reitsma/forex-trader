from datetime import UTC, datetime
from decimal import Decimal

import httpx

import forex_trader.adapters.oanda_safe as oanda_safe_module
from forex_trader.adapters.oanda_safe import SafeOandaPracticeClient


class FrozenDateTime(datetime):
    @classmethod
    def now(cls, tz=None):  # type: ignore[no-untyped-def]
        value = cls(2026, 8, 7, 20, 0, tzinfo=UTC)
        return value if tz is None else value.astimezone(tz)


def test_realized_pl_aggregates_from_5pm_new_york_and_caches(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.setattr(oanda_safe_module, "datetime", FrozenDateTime)
    client = httpx.Client(transport=httpx.MockTransport(lambda request: httpx.Response(500)))
    oanda = SafeOandaPracticeClient(token="token", account_id="A", client=client)
    calls: list[tuple[datetime, datetime]] = []

    def transactions_between(start: datetime, end: datetime):  # type: ignore[no-untyped-def]
        calls.append((start, end))
        return [
            {
                "pl": "10",
                "financing": "-1",
                "commission": "-0.5",
                "guaranteedExecutionFee": "0",
                "dividendAdjustment": "0",
            },
            {"pl": "-2", "financing": "0.25"},
        ]

    monkeypatch.setattr(oanda, "transactions_between", transactions_between)
    first = oanda.realized_pl_today()
    second = oanda.realized_pl_today()
    assert first == Decimal("6.75")
    assert second == first
    assert len(calls) == 1
    start, end = calls[0]
    assert start == datetime(2026, 8, 6, 21, 0, tzinfo=UTC)
    assert end == datetime(2026, 8, 7, 20, 0, tzinfo=UTC)
