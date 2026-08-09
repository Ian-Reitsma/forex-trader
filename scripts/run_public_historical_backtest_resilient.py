from __future__ import annotations

import importlib
import sys
from pathlib import Path
from typing import Callable, cast

from forex_trader.research.gdelt_history import ResilientGdeltDocHistoryClient


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

campaign = importlib.import_module("scripts.run_public_historical_backtest")
setattr(campaign, "GdeltDocHistoryClient", ResilientGdeltDocHistoryClient)
main = cast(Callable[[], int], getattr(campaign, "main"))


if __name__ == "__main__":
    raise SystemExit(main())
