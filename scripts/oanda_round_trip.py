"""Open, verify protection, and immediately close the broker minimum on OANDA Practice.

This is an explicit credential/order-path verification tool, not a strategy test. It
refuses to run unless paper mode, paper-order gate, token and explicit account ID are
configured. The token is never printed and identifiers are reduced to suffixes.
"""
from __future__ import annotations

import json
from decimal import Decimal
from uuid import uuid4

from forex_trader.adapters.oanda_safe import SafeOandaPracticeClient
from forex_trader.config import AppConfig
from forex_trader.domain.enums import Direction, OperatingMode, OrderStatus, ProviderKind
from forex_trader.domain.models import OrderRequest

config = AppConfig.from_env()
if config.provider is not ProviderKind.OANDA:
    raise SystemExit("FOREX_PROVIDER must be oanda")
if config.mode is not OperatingMode.PAPER or not config.enable_paper_orders:
    raise SystemExit("FOREX_MODE=paper and FOREX_ENABLE_PAPER_ORDERS=true are required")
if not config.oanda_token:
    raise SystemExit("OANDA_API_TOKEN is required")
if not config.oanda_account_id:
    raise SystemExit("OANDA_ACCOUNT_ID is required for Practice broker writes")
instrument = config.instruments[0]
with SafeOandaPracticeClient(
    token=config.oanda_token,
    account_id=config.oanda_account_id,
    rest_url=config.oanda_rest_url,
    stream_url=config.oanda_stream_url,
    timeout_seconds=config.oanda_timeout_seconds,
) as client:
    if client.has_open_position(instrument):
        raise SystemExit(f"refusing round-trip test: {instrument} already has an open position")
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
        raise SystemExit(f"practice order did not produce a reconciled fill; status={result.status}")
    protected = client.ensure_trade_protection(
        result.provider_trade_id,
        stop_loss=stop,
        take_profit=target,
    )
    if not protected:
        client.close_trade(result.provider_trade_id)
        raise SystemExit("practice fill was not verifiably protected; emergency close attempted")
    close_payload = client.close_trade(result.provider_trade_id)
    if client.has_open_position(instrument):
        raise SystemExit("round-trip close returned but the instrument remains open")
    print(
        json.dumps(
            {
                "status": "protected_round_trip_completed",
                "instrument": instrument,
                "units": units,
                "fill_price": str(result.fill_price),
                "price_bound": str(bound),
                "protection_confirmed": protected,
                "order_id_suffix": (result.provider_order_id or "")[-6:],
                "trade_id_suffix": result.provider_trade_id[-6:],
                "close_transaction_present": bool(close_payload.get("orderFillTransaction")),
                "open_position_after_close": False,
            },
            indent=2,
            sort_keys=True,
        )
    )
