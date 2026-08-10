"""Synchronize prospective licensed Trading Economics calendar evidence into the local macro ledger.

The credential is read only from TRADING_ECONOMICS_API_KEY. Vendor rows are never backdated:
a release first becomes available to the strategy at the timestamp this process actually retrieved it.
"""
from __future__ import annotations

import json

from forex_trader.application.trading_economics_sync import sync_trading_economics_fundamentals
from forex_trader.config import AppConfig
from forex_trader.ingestion.trading_economics import TradingEconomicsSettings

config = AppConfig.from_env()
settings = TradingEconomicsSettings.from_env()
try:
    settings.validate()
except ValueError as exc:
    raise SystemExit(str(exc)) from exc

try:
    report = sync_trading_economics_fundamentals(config.database_path, settings)
except Exception as exc:
    raise SystemExit(f"Trading Economics sync failed closed: {type(exc).__name__}: {exc}") from exc

print(json.dumps(report.to_jsonable(), indent=2, sort_keys=True))
