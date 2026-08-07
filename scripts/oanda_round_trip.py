"""Open, verify protection, and immediately close the broker minimum on OANDA Practice.

This is an explicit credential/order-path verification tool, not a strategy test. It
refuses to run unless paper mode, paper-order gate, token and explicit account ID are
configured. The token is never printed and identifiers are reduced to suffixes.
"""
from __future__ import annotations

import json

from forex_trader.adapters.oanda_safe import SafeOandaPracticeClient
from forex_trader.application.practice_round_trip import (
    PracticeRoundTripError,
    run_practice_round_trip,
)
from forex_trader.config import AppConfig
from forex_trader.domain.enums import OperatingMode, ProviderKind

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

try:
    with SafeOandaPracticeClient(
        token=config.oanda_token,
        account_id=config.oanda_account_id,
        rest_url=config.oanda_rest_url,
        stream_url=config.oanda_stream_url,
        timeout_seconds=config.oanda_timeout_seconds,
    ) as client:
        report = run_practice_round_trip(client, instrument)
except PracticeRoundTripError as exc:
    raise SystemExit(str(exc)) from None

print(
    json.dumps(
        {
            "status": "protected_round_trip_completed",
            "instrument": report.instrument,
            "units": report.units,
            "fill_price": str(report.fill_price),
            "price_bound": str(report.price_bound),
            "protection_confirmed": report.protection_confirmed,
            "order_id_suffix": (report.provider_order_id or "")[-6:],
            "trade_id_suffix": report.provider_trade_id[-6:],
            "close_transaction_present": report.close_transaction_present,
            "open_position_after_close": False,
        },
        indent=2,
        sort_keys=True,
    )
)
