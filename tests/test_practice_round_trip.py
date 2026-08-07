from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

import pytest

from forex_trader.application.practice_round_trip import (
    PracticeRoundTripError,
    run_practice_round_trip,
)
from forex_trader.domain.enums import OrderStatus
from forex_trader.domain.models import InstrumentSpec, OrderResult, Quote


class FakePracticeClient:
    def __init__(self, *, order_status: OrderStatus = OrderStatus.FILLED) -> None:
        self.spec = InstrumentSpec(
            name="EUR_USD",
            display_precision=5,
            pip_location=-4,
            trade_units_precision=0,
            minimum_trade_size=Decimal("1"),
        )
        self.quote = Quote(
            "EUR_USD",
            Decimal("1.09990"),
            Decimal("1.10000"),
            datetime(2026, 8, 7, 14, 0, tzinfo=UTC),
        )
        self.order_status = order_status
        self.open = False
        self.close_calls = 0
        self.protection_result = True
        self.protection_error: Exception | None = None
        self.close_error: Exception | None = None
        self.reconciled: OrderResult | None = None
        self.request = None

    def has_open_position(self, instrument: str) -> bool:
        return self.open

    def instrument_spec(self, instrument: str) -> InstrumentSpec:
        return self.spec

    def quote_for_units(self, instrument: str, units: int) -> Quote:
        return self.quote

    def place_market_order(self, request):  # type: ignore[no-untyped-def]
        self.request = request
        if self.order_status is OrderStatus.FILLED:
            self.open = True
            return _filled(request.client_order_id)
        return OrderResult(
            request.client_order_id,
            None,
            self.order_status,
            request.instrument,
            request.units,
            None,
        )

    def reconcile_order(self, **kwargs):  # type: ignore[no-untyped-def]
        if self.reconciled is not None and self.reconciled.status is OrderStatus.FILLED:
            self.open = True
        return self.reconciled

    def ensure_trade_protection(self, trade_id: str, *, stop_loss, take_profit):  # type: ignore[no-untyped-def]
        if self.protection_error is not None:
            raise self.protection_error
        return self.protection_result

    def close_trade(self, trade_id: str):  # type: ignore[no-untyped-def]
        self.close_calls += 1
        if self.close_error is not None:
            raise self.close_error
        self.open = False
        return {"orderFillTransaction": {"id": "close-1"}}


def _filled(client_order_id: str = "probe") -> OrderResult:
    return OrderResult(
        client_order_id=client_order_id,
        provider_order_id="order-123456",
        status=OrderStatus.FILLED,
        instrument="EUR_USD",
        units=1,
        fill_price=Decimal("1.10000"),
        provider_trade_id="trade-654321",
    )


def test_successful_round_trip_verifies_protection_and_closes() -> None:
    client = FakePracticeClient()
    report = run_practice_round_trip(client, "eur_usd")  # type: ignore[arg-type]

    assert report.instrument == "EUR_USD"
    assert report.units == 1
    assert report.protection_confirmed is True
    assert report.close_transaction_present is True
    assert client.close_calls == 1
    assert client.open is False
    assert client.request.stop_loss == Decimal("1.09900")
    assert client.request.take_profit == Decimal("1.10100")
    assert client.request.price_bound == Decimal("1.10010")


def test_unprotected_fill_is_closed_before_failure() -> None:
    client = FakePracticeClient()
    client.protection_result = False

    with pytest.raises(PracticeRoundTripError, match="not verifiably protected"):
        run_practice_round_trip(client, "EUR_USD")  # type: ignore[arg-type]

    assert client.close_calls == 1
    assert client.open is False


def test_protection_exception_still_closes_before_failure() -> None:
    client = FakePracticeClient()
    client.protection_error = RuntimeError("verification unavailable")

    with pytest.raises(PracticeRoundTripError, match="protection verification/repair raised"):
        run_practice_round_trip(client, "EUR_USD")  # type: ignore[arg-type]

    assert client.close_calls == 1
    assert client.open is False


def test_close_failure_is_critical_and_does_not_claim_success() -> None:
    client = FakePracticeClient()
    client.close_error = RuntimeError("close unavailable")

    with pytest.raises(PracticeRoundTripError, match="CRITICAL"):
        run_practice_round_trip(client, "EUR_USD")  # type: ignore[arg-type]

    assert client.close_calls == 1
    assert client.open is True


def test_unknown_order_can_reconcile_to_known_fill_then_close() -> None:
    client = FakePracticeClient(order_status=OrderStatus.UNKNOWN)
    client.reconciled = _filled("reconciled-probe")

    report = run_practice_round_trip(client, "EUR_USD")  # type: ignore[arg-type]

    assert report.provider_trade_id == "trade-654321"
    assert client.close_calls == 1
    assert client.open is False


def test_unreconciled_unknown_fails_without_submitting_another_order() -> None:
    client = FakePracticeClient(order_status=OrderStatus.UNKNOWN)

    with pytest.raises(PracticeRoundTripError, match="did not produce a reconciled fill"):
        run_practice_round_trip(client, "EUR_USD")  # type: ignore[arg-type]

    assert client.close_calls == 0
    assert client.open is False


def test_existing_position_blocks_probe_before_order_submission() -> None:
    client = FakePracticeClient()
    client.open = True

    with pytest.raises(PracticeRoundTripError, match="already has an open position"):
        run_practice_round_trip(client, "EUR_USD")  # type: ignore[arg-type]

    assert client.request is None
    assert client.close_calls == 0


def test_blank_instrument_is_rejected() -> None:
    with pytest.raises(ValueError, match="instrument is required"):
        run_practice_round_trip(FakePracticeClient(), "  ")  # type: ignore[arg-type]
