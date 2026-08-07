"""Chronological score-threshold calibration using OANDA Practice history.

Uses the same configured lower/higher timeframe policy as runtime. Defaults to persisted
point-in-time macro/news observations. Threshold selection uses rolling development folds
and reports a final untouched holdout. Historical OANDA bars are midpoint OHLC; this
script is research evidence, not a fill-quality simulation.
"""
from __future__ import annotations

import argparse
import json
from datetime import UTC, datetime, timedelta
from decimal import Decimal

from forex_trader.adapters.oanda_safe import SafeOandaPracticeClient
from forex_trader.config import AppConfig, load_macro_file
from forex_trader.domain.fundamentals import FundamentalBook
from forex_trader.domain.macro_history import PointInTimeFundamentalBook
from forex_trader.domain.models import CurrencyFundamentals, jsonable
from forex_trader.domain.strategy import SignalFusionPolicy
from forex_trader.domain.timeframes import granularity_duration
from forex_trader.infrastructure.trading_repository import TradingRepository
from forex_trader.research.backtest import run_walk_forward_backtest
from forex_trader.research.validation import rolling_threshold_validation

parser = argparse.ArgumentParser()
parser.add_argument("--instrument", default=None)
parser.add_argument("--days", type=int, default=180)
parser.add_argument("--spread-pips", type=Decimal, default=Decimal("1.0"))
parser.add_argument("--technical-only", action="store_true")
parser.add_argument("--train-size", type=int, default=80)
parser.add_argument("--validation-size", type=int, default=40)
parser.add_argument("--step", type=int, default=40)
parser.add_argument("--minimum-training-trades", type=int, default=20)
args = parser.parse_args()

config = AppConfig.from_env()
if not config.oanda_token:
    raise SystemExit("OANDA_API_TOKEN is required")
instrument = (args.instrument or config.instruments[0]).upper()
base, quote = instrument.split("_", maxsplit=1)
lower_tf = config.lower_timeframe
higher_tf = config.higher_timeframe
lower_duration = granularity_duration(lower_tf)
higher_duration = granularity_duration(higher_tf)
repo = TradingRepository(config.database_path)
if args.technical_only:
    fundamentals: FundamentalBook | PointInTimeFundamentalBook = FundamentalBook([
        CurrencyFundamentals(base, confidence=Decimal("0"), as_of=datetime(2000, 1, 1, tzinfo=UTC)),
        CurrencyFundamentals(quote, confidence=Decimal("0"), as_of=datetime(2000, 1, 1, tzinfo=UTC)),
    ])
else:
    observations = repo.macro_observations()
    if not observations:
        raise SystemExit("point-in-time macro history is empty; import history or use --technical-only")
    fundamentals = PointInTimeFundamentalBook(
        observations,
        seeds=load_macro_file(None, use_demo_defaults=False).snapshots(),
    )

end = datetime.now(UTC)
start = end - timedelta(days=args.days)
higher_warmup_start = start - max(timedelta(days=10), higher_duration * 100)
with SafeOandaPracticeClient(
    token=config.oanda_token,
    account_id=config.oanda_account_id,
    rest_url=config.oanda_rest_url,
    stream_url=config.oanda_stream_url,
    timeout_seconds=config.oanda_timeout_seconds,
) as client:
    spec = client.instrument_spec(instrument)
    lower = client.candles_between(instrument, lower_tf, start, end)
    higher = client.candles_between(instrument, higher_tf, higher_warmup_start, end)

trades, baseline = run_walk_forward_backtest(
    instrument=instrument,
    lower_candles=lower,
    higher_candles=higher,
    fundamentals=fundamentals,
    fusion_policy=SignalFusionPolicy(
        minimum_score=Decimal("0.50"),
        maximum_spread_pips=config.maximum_spread_pips,
        require_fundamentals=not args.technical_only,
    ),
    spread_pips=args.spread_pips,
    lower_timeframe=lower_duration,
    higher_timeframe=higher_duration,
)
try:
    validation = rolling_threshold_validation(
        trades,
        train_size=args.train_size,
        validation_size=args.validation_size,
        step=args.step,
        minimum_training_trades=args.minimum_training_trades,
    )
except ValueError as exc:
    raise SystemExit(f"insufficient trade history for rolling validation: {exc}") from exc

print(json.dumps({
    "scope": "technical-only" if args.technical_only else "point-in-time combined",
    "instrument": instrument,
    "timeframe_policy": {"lower": lower_tf, "higher": higher_tf},
    "pip_size": str(spec.pip_size),
    "baseline": jsonable(baseline),
    "rolling_validation": jsonable(validation),
    "adoption_rule": (
        "Do not change the production threshold from this output alone. Require positive "
        "untouched-holdout expectancy, stressed execution resilience and stability across multiple instruments/windows."
    ),
}, indent=2, sort_keys=True))
