from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from uuid import uuid4

from forex_trader.adapters.oanda_safe import SafeOandaPracticeClient
from forex_trader.domain.enums import Direction, OrderStatus
from forex_trader.domain.models import OrderRequest


class PracticeRoundTripError(RuntimeError):
    """Raised when the broker-minimum Practice probe cannot prove a safe round trip."""


@dataclass(frozen=True, slots=True)
class PracticeRoundTripReport:
    instrument: str
    units: int
    fill_price: Decimal | None
    price_bound: Decimal
    protection_confirmed: bool
    provider_order_id: str | None
    provider_trade_id: str
    close_transaction_present: bool


def run_practice_round_trip(
    client: SafeOandaPracticeClient,
    instrument: str,
) -> PracticeRoundTripReport:
    """Open the broker minimum, verify protection, and close it again.

    This is execution-path validation, not a strategy decision. Once a fill with a known
    trade ID exists, a close is attempted regardless of whether protection verification
    succeeds, returns false, or raises. Any inability to prove the close is treated as a
    critical reconciliation condition and no further broker risk should be taken.
    """
    instrument = instrument.strip().upper()
    if not instrument:
        raise ValueError("instrument is required")
    if client.has_open_position(instrument):
        raise PracticeRoundTripError(
            f"refusing round-trip test: {instrument} already has an open position"
        )

    spec = client.instrument_spec(instrument)
    units = int(max(Decimal("1"), spec.minimum_trade_size))
    quote = client.quote_for_units(instrument, units)
    stop = quote.ask - spec.pip_size * Decimal("10")
    target = quote.ask + spec.pip_size * Decimal("10")
    bound = quote.ask + spec.pip_size * Decimal("1")

    result = client.place_market_order(
        OrderRequest(
            client_order_id=f"probe-{uuid4().hex[:20]}",
            instrument=instrument,
            direction=Direction.LONG,
            units=units,
            stop_loss=stop,
            take_profit=target,
            execution_key=f"practice-probe-{uuid4().hex[:24]}",
            intended_price=quote.ask,
            price_bound=bound,
            authorization_id="explicit-practice-probe",
        )
    )
    if result.status is OrderStatus.UNKNOWN:
        reconciled = client.reconcile_order(
            client_order_id=result.client_order_id,
            instrument=instrument,
            units=units,
        )
        result = reconciled or result

    if result.status is not OrderStatus.FILLED or result.provider_trade_id is None:
        unresolved_position = False
        try:
            unresolved_position = client.has_open_position(instrument)
        except Exception:
            unresolved_position = True
        detail = (
            " An open/unverifiable position may exist; manually reconcile the Practice "
            "account before any further order."
            if unresolved_position
            else ""
        )
        raise PracticeRoundTripError(
            f"practice order did not produce a reconciled fill; status={result.status.value}.{detail}"
        )

    trade_id = result.provider_trade_id
    protection_confirmed = False
    protection_error: Exception | None = None
    close_payload: dict[str, object] = {}

    try:
        try:
            protection_confirmed = client.ensure_trade_protection(
                trade_id,
                stop_loss=stop,
                take_profit=target,
            )
        except Exception as exc:  # broker/provider failure must still enter the close path
            protection_error = exc
    finally:
        try:
            raw_close = client.close_trade(trade_id)
            if isinstance(raw_close, dict):
                close_payload = raw_close
        except Exception as exc:
            raise PracticeRoundTripError(
                "CRITICAL: the Practice probe filled but the close attempt failed or was "
                "unverifiable; manually reconcile/close the Practice trade before any "
                "further broker write"
            ) from exc

    try:
        remains_open = client.has_open_position(instrument)
    except Exception as exc:
        raise PracticeRoundTripError(
            "CRITICAL: the close request returned but post-close position state could not "
            "be verified; manually reconcile the Practice account before any further write"
        ) from exc
    if remains_open:
        raise PracticeRoundTripError(
            "CRITICAL: the round-trip close returned but the instrument remains open; "
            "manually reconcile/close it before any further broker write"
        )
    if protection_error is not None:
        raise PracticeRoundTripError(
            "Practice protection verification/repair raised an exception; the probe trade "
            "was closed, but broker protection behavior must be resolved before a campaign"
        ) from protection_error
    if not protection_confirmed:
        raise PracticeRoundTripError(
            "Practice fill was not verifiably protected; the probe trade was closed and "
            "campaign execution must remain disabled"
        )

    return PracticeRoundTripReport(
        instrument=instrument,
        units=units,
        fill_price=result.fill_price,
        price_bound=bound,
        protection_confirmed=True,
        provider_order_id=result.provider_order_id,
        provider_trade_id=trade_id,
        close_transaction_present=bool(close_payload.get("orderFillTransaction")),
    )
