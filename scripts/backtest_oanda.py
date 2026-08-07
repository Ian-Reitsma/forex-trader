"""Point-in-time OANDA Practice candle replay with explicit execution stress.

Uses the same configured lower/higher timeframe policy as runtime. Persisted immutable
macro/news observations are used by default. OANDA historical candles are midpoint bars,
so spread/slippage inputs remain modeled until a true historical bid/ask or tick archive
is connected. The token is read from the environment and never printed.
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

parser = argparse.ArgumentParser()
parser.add_argument("--instrument", default=None)
parser.add_argument("--days", type=int, default=90)
parser.add_argument("--spread-pips", type=Decimal, default=Decimal("1.0"))
parser.add_argument("--stress-spread-multiplier", type=Decimal, default=Decimal("1.75"))
parser.add_argument("--stress-entry-slippage-pips", type=Decimal, default=Decimal("0.35"))
parser.add_argument("--stress-exit-slippage-pips", type=Decimal, default=Decimal("0.50"))
parser.add_argument("--stress-entry-delay-bars", type=int, default=1)
parser.add_argument("--technical-only", action="store_true")
args = parser.parse_args()

if args.days < 7:
    raise SystemExit("--days must be at least 7")
if args.spread_pips < 0 or args.stress_spread_multiplier < 1:
    raise SystemExit("spread must be non-negative and stress multiplier must be >= 1")
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
    fundamentals: FundamentalBook | PointInTimeFundamentalBook = FundamentalBook(
        [
            CurrencyFundamentals(base, confidence=Decimal("0"), as_of=datetime(2000, 1, 1, tzinfo=UTC)),
            CurrencyFundamentals(quote, confidence=Decimal("0"), as_of=datetime(2000, 1, 1, tzinfo=UTC)),
        ]
    )
else:
    seeds = load_macro_file(None, use_demo_defaults=False).snapshots()
    observations = repo.macro_observations()
    if not observations:
        raise SystemExit(
            "no persisted point-in-time macro observations are available; ingest/import "
            "historical releases/news first or use --technical-only for diagnostics"
        )
    fundamentals = PointInTimeFundamentalBook(observations, seeds=seeds)

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

policy = SignalFusionPolicy(
    minimum_score=config.minimum_score,
    maximum_spread_pips=config.maximum_spread_pips,
    require_fundamentals=not args.technical_only,
)
base_trades, base_report = run_walk_forward_backtest(
    instrument=instrument,
    lower_candles=lower,
    higher_candles=higher,
    fundamentals=fundamentals,
    fusion_policy=policy,
    spread_pips=args.spread_pips,
    lower_timeframe=lower_duration,
    higher_timeframe=higher_duration,
)
stress_trades, stress_report = run_walk_forward_backtest(
    instrument=instrument,
    lower_candles=lower,
    higher_candles=higher,
    fundamentals=fundamentals,
    fusion_policy=policy,
    spread_pips=args.spread_pips * args.stress_spread_multiplier,
    entry_slippage_pips=args.stress_entry_slippage_pips,
    exit_slippage_pips=args.stress_exit_slippage_pips,
    entry_delay_bars=args.stress_entry_delay_bars,
    lower_timeframe=lower_duration,
    higher_timeframe=higher_duration,
)
print(
    json.dumps(
        {
            "scope": "technical-only" if args.technical_only else "point-in-time combined",
            "instrument": instrument,
            "timeframe_policy": {"lower": lower_tf, "higher": higher_tf},
            "pip_size": str(spec.pip_size),
            "start": start.isoformat(),
            "end": end.isoformat(),
            "historical_price_limitation": "OANDA candle history is midpoint OHLC; modeled costs are not a substitute for historical executable bid/ask ticks.",
            "baseline": {
                "report": jsonable(base_report),
                "evaluated_trades": len(base_trades),
                "spread_pips": str(args.spread_pips),
            },
            "stress": {
                "report": jsonable(stress_report),
                "evaluated_trades": len(stress_trades),
                "spread_pips": str(args.spread_pips * args.stress_spread_multiplier),
                "entry_slippage_pips": str(args.stress_entry_slippage_pips),
                "exit_slippage_pips": str(args.stress_exit_slippage_pips),
                "entry_delay_bars": args.stress_entry_delay_bars,
            },
        },
        indent=2,
        sort_keys=True,
    )
)
