"""Technical-only OANDA Practice candle replay.

This script intentionally does not claim to validate the combined fundamental strategy.
Historical point-in-time macro and news observations must be added before that claim is valid.
The token is read from the environment and is never printed.
"""
from __future__ import annotations

import argparse
from decimal import Decimal

from forex_trader.adapters.oanda import OandaPracticeClient
from forex_trader.config import AppConfig
from forex_trader.domain.fundamentals import FundamentalBook
from forex_trader.domain.models import CurrencyFundamentals, jsonable
from forex_trader.domain.strategy import SignalFusionPolicy
from forex_trader.research.backtest import run_walk_forward_backtest


parser = argparse.ArgumentParser()
parser.add_argument("--instrument", default=None)
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
    client.instrument_spec(instrument)
    trades, report = run_walk_forward_backtest(
        instrument=instrument,
        lower_candles=lower,
        higher_candles=higher,
        fundamentals=neutral_fundamentals,
        fusion_policy=SignalFusionPolicy(
            minimum_score=config.minimum_score,
            maximum_spread_pips=config.maximum_spread_pips,
            require_fundamentals=False,
        ),
        spread_pips=args.spread_pips,
    )
print(jsonable(report))
print(f"evaluated trades: {len(trades)}")
