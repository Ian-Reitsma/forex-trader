"""Synchronize free official macro evidence into the local point-in-time ledger."""
from __future__ import annotations

import json

from forex_trader.application.free_official_sync import sync_free_official_fundamentals
from forex_trader.config import AppConfig

config = AppConfig.from_env()
report = sync_free_official_fundamentals(config.database_path)
print(json.dumps(report.to_jsonable(), indent=2, sort_keys=True))

if report.status == "unavailable":
    raise SystemExit("free official fundamentals sync failed: no supported currency source succeeded")
if report.status == "degraded":
    print("free official fundamentals sync degraded: one or more supported currency sources failed")
