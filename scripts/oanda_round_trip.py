"""Open and immediately close the broker minimum on OANDA Practice.

This is an explicit credential and order-path verification tool, not a strategy test.
It refuses to run unless paper mode and the paper-order gate are both enabled. The token
is never printed. Use only with the fxPractice endpoint.
"""
from __future__ import annotations

import json
from decimal import Decimal
from uuid import uuid4

from forex_trader.adapters.oanda import OandaApiError, OandaPracticeClient
from forex_trader.config import AppConfig
from forex_trader.domain.enums import Direction, OperatingMode, ProviderKind
from forex_trader.domain.models import OrderRequest

config = AppConfig.from_env()
if config.provider is not ProviderKind.OANDA:
    raise SystemExit("FOREX_PROVIDER must be oanda")
if config.mode is not OperatingMode.PAPER or not config.enable_paper_orders:
    raise SystemExit("FOREX_MODE=paper and FOREX_ENABLE_PAPER_ORDERS=true are required")
if not config.oanda_token:
    raise SystemExit("OANDA_API_TOKEN is required")
instrument = config.instruments[0]
with OandaPracticeClient(
    token=config.oanda_token,
    account_id=config.oanda_account_id,
    rest_url=config.oanda_rest_url,
    stream_url=config.oanda_stream_url,
    timeout_seconds=config.oanda_timeout_seconds,
) as client:
    if client.has_open_position(instrument):
        raise SystemExit(f"refusing round-trip test: {instrument} already has an open position")
    spec = client.instrument_spec(instrument)
    quote = client.quote(instrument)
    units = int(max(Decimal("1"), spec.minimum_trade_size))
    stop = quote.ask - spec.pip_size * Decimal("10")
    target = quote.ask + spec.pip_size * Decimal("10")
    result = client.place_market_order(
        OrderRequest(
            client_order_id=f"probe-{uuid4().hex[:20]}",
            instrument=instrument,
            direction=Direction.LONG,
            units=units,
            stop_loss=stop,
            take_profit=target,
            execution_key=f"practice-probe-{uuid4().hex[:24]}",
        )
    )
    if result.provider_trade_id is None:
        raise SystemExit(f"practice order did not open a new trade; status={result.status}")
    close_payload = client.close_trade(result.provider_trade_id)
    print(
        json.dumps(
            {
                "status": "round_trip_completed",
                "instrument": instrument,
                "units": units,
                "fill_price": str(result.fill_price),
                "order_id_suffix": (result.provider_order_id or "")[-6:],
                "trade_id_suffix": result.provider_trade_id[-6:],
                "close_transaction_present": bool(close_payload.get("orderFillTransaction")),
            },
            indent=2,
            sort_keys=True,
        )
    )
