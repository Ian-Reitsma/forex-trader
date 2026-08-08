from __future__ import annotations

import argparse
import asyncio
import importlib
import json
import sys
from collections.abc import Callable, Coroutine
from pathlib import Path
from types import ModuleType
from typing import Any, cast

from forex_trader.research.official_news_history import (
    OfficialCentralBankHistoryClient,
    official_news_observations,
)


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

campaign: ModuleType = importlib.import_module("scripts.run_public_historical_backtest")
setattr(campaign, "GdeltDocHistoryClient", OfficialCentralBankHistoryClient)
setattr(campaign, "gdelt_news_observations", official_news_observations)
_campaign_run = cast(
    Callable[[argparse.Namespace], Coroutine[Any, Any, dict[str, object]]],
    getattr(campaign, "run"),
)
_jsonable = cast(Callable[[object], object], getattr(campaign, "_jsonable"))


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Run exact bid/ask FX backtesting with first-party central-bank historical news."
    )
    parser.add_argument("--instruments", default="EUR_USD,GBP_USD,USD_JPY")
    parser.add_argument("--start")
    parser.add_argument("--end")
    parser.add_argument("--days", type=int, default=35)
    parser.add_argument("--lag-days", type=int, default=7)
    parser.add_argument("--cache-dir", default=".cache/forex-trader/public-history")
    parser.add_argument("--output", default="artifacts/public-historical-backtest.json")
    parser.add_argument("--concurrency-per-pair", type=int, default=10)
    parser.add_argument("--maximum-holding-minutes", type=int, default=120)
    parser.add_argument("--entry-latency-ms", type=int, default=500)
    parser.add_argument("--slippage-pips", default="0.10")
    parser.add_argument("--minimum-calibration-trades", type=int, default=12)
    args = parser.parse_args()

    report = asyncio.run(_campaign_run(args))
    report["data_sources"] = {
        "price": "Dukascopy public historical BI5 best bid/ask ticks",
        "news": (
            "First-party monetary-policy/news feeds from the Federal Reserve, European Central Bank, "
            "Bank of England, and Bank of Japan"
        ),
        "limitations": [
            "Official central-bank publications do not replace point-in-time economic-consensus releases such as CPI/NFP forecasts.",
            "Publication timestamps come from first-party feed metadata and are never moved earlier than their published time.",
            "Dukascopy best-quote volume is not treated as centralized institutional traded volume.",
            "No OANDA credential or live-money endpoint is used by this backtest.",
        ],
    }
    report["news_source_mode"] = "official_central_bank_first_party"
    rendered = json.dumps(_jsonable(report), indent=2, sort_keys=True)
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(rendered + "\n", encoding="utf-8")
    print(rendered)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
