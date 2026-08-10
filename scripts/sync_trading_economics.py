"""Synchronize prospective licensed Trading Economics calendar evidence into the local macro ledger.

The credential is read only from TRADING_ECONOMICS_API_KEY. Vendor rows are never backdated:
a release first becomes available to the strategy at the timestamp this process actually retrieved it.
"""
from __future__ import annotations

import json
from hmac import compare_digest

from forex_trader.application.trading_economics_sync import sync_trading_economics_fundamentals
from forex_trader.config import AppConfig
from forex_trader.ingestion.trading_economics import TradingEconomicsSettings

config = AppConfig.from_env()
settings = TradingEconomicsSettings.from_env()
try:
    settings.validate()
except ValueError as exc:
    raise SystemExit(str(exc)) from exc

if settings.api_key is not None:
    if config.api_token is not None and compare_digest(settings.api_key, config.api_token):
        raise SystemExit(
            "TRADING_ECONOMICS_API_KEY is cross-wired to FOREX_API_TOKEN. "
            "Use a credential issued by Trading Economics; the forex-trader control-plane token cannot authenticate Trading Economics."
        )
    if config.oanda_token is not None and compare_digest(settings.api_key, config.oanda_token):
        raise SystemExit(
            "TRADING_ECONOMICS_API_KEY is cross-wired to OANDA_API_TOKEN. "
            "Use a credential issued by Trading Economics; the OANDA Practice token cannot authenticate Trading Economics."
        )

try:
    report = sync_trading_economics_fundamentals(config.database_path, settings)
except Exception as exc:
    raise SystemExit(f"Trading Economics sync failed closed: {type(exc).__name__}: {exc}") from exc

print(json.dumps(report.to_jsonable(), indent=2, sort_keys=True))
