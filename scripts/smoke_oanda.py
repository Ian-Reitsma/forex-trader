"""Read-only OANDA Practice smoke test through the production Practice adapter.

Run with OANDA_API_TOKEN and optionally OANDA_ACCOUNT_ID set. The token is never printed,
and account identifiers are reduced to a suffix.
"""
from __future__ import annotations

import json

from forex_trader.adapters.oanda import OandaApiError
from forex_trader.adapters.oanda_safe import SafeOandaPracticeClient
from forex_trader.config import AppConfig

config = AppConfig.from_env()
if not config.oanda_token:
    raise SystemExit("OANDA_API_TOKEN is required")
try:
    with SafeOandaPracticeClient(
        token=config.oanda_token,
        account_id=config.oanda_account_id,
        rest_url=config.oanda_rest_url,
        stream_url=config.oanda_stream_url,
        timeout_seconds=config.oanda_timeout_seconds,
    ) as client:
        payload = client.practice_probe(config.instruments[0])
        specs = client.currency_instruments()
        payload["currency_instruments"] = len(specs)
        payload["sample_instruments"] = [spec.name for spec in specs[:10]]
except OandaApiError as exc:
    print(json.dumps({"status": "failed", "error": str(exc)}, indent=2, sort_keys=True))
    raise SystemExit(2) from None
print(json.dumps(payload, indent=2, sort_keys=True))
