"""Walk-forward threshold calibration using recent OANDA Practice candles.

This is a technical-only calibration because the repository does not yet persist historical,
point-in-time economic releases and news. It never submits orders and never prints the token.
The selected threshold is trained on the first chronological fold and reported separately on
an untouched validation fold.
"""
from __future__ import annotations

import argparse
import json
from decimal import Decimal

from forex_trader.adapters.oanda import OandaPracticeClient
from forex_trader.config import AppConfig
from forex_trader.domain.fundamentals import FundamentalBook
from forex_trader.domain.models import CurrencyFundamentals, jsonable
from forex_trader.domain.strategy import SignalFusionPolicy
from forex_trader.research.backtest import (
    optimize_score_threshold,
    run_walk_forward_backtest,
    summarize_trades,
)


parser = argparse.ArgumentParser()
parser.add_argument("--instrument", default=None)
parser.add_argument("--minimum-trades", type=int, default=10)
parser.add_argument("--spread-pips", type=Decimal, default=Decimal("1.0"))
args = parser.parse_args()

config = AppConfig.from_env()
if not config.oanda_token:
    raise SystemExit("OANDA_API_TOKEN is required")
instrument = (args.instrument or config.instruments[0]).upper()
base, quote = instrument.split("_", maxsplit=1)
neutral_fundamentals = FundamentalBook(
    [
        CurrencyFundamentals(base, confidence=Decimal("0")),
        CurrencyFundamentals(quote, confidence=Decimal("0")),
    ]
)
with OandaPracticeClient(
    token=config.oanda_token,
    account_id=config.oanda_account_id,
    rest_url=config.oanda_rest_url,
    timeout_seconds=config.oanda_timeout_seconds,
) as client:
    lower = client.candles(instrument, "M5", 5000)
    higher = client.candles(instrument, "H1", 1000)

trades, baseline = run_walk_forward_backtest(
    instrument=instrument,
    lower_candles=lower,
    higher_candles=higher,
    fundamentals=neutral_fundamentals,
    fusion_policy=SignalFusionPolicy(
        minimum_score=Decimal("0.50"),
        maximum_spread_pips=config.maximum_spread_pips,
        require_fundamentals=False,
    ),
    spread_pips=args.spread_pips,
)
if len(trades) < args.minimum_trades * 2:
    raise SystemExit(
        f"only {len(trades)} trades were available; collect more history before calibration"
    )
split = max(args.minimum_trades, int(len(trades) * 0.70))
training = trades[:split]
validation = trades[split:]
selected = optimize_score_threshold(training, minimum_trades=args.minimum_trades)
validation_report = summarize_trades(validation, minimum_score=selected.minimum_score)
print(
    json.dumps(
        {
            "scope": "technical-only; no historical fundamentals",
            "instrument": instrument,
            "baseline": jsonable(baseline),
            "training_selected": jsonable(selected),
            "validation": jsonable(validation_report),
            "adoption_rule": (
                "Do not change FOREX_MINIMUM_SCORE unless the untouched validation fold "
                "has positive expectancy, acceptable drawdown, and sufficient sample size."
            ),
        },
        indent=2,
        sort_keys=True,
    )
)
