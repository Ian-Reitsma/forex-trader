"""Point-in-time OANDA Practice candle replay.

Uses persisted immutable macro/news observations by default. Use --technical-only only
for diagnostic comparison. The OANDA token is read from the environment and never printed.
"""
from __future__ import annotations

import argparse
import json
from datetime import UTC, datetime, timedelta
from decimal import Decimal

from forex_trader.adapters.oanda import OandaPracticeClient
from forex_trader.config import AppConfig, load_macro_file
from forex_trader.domain.fundamentals import FundamentalBook
from forex_trader.domain.macro_history import PointInTimeFundamentalBook
from forex_trader.domain.models import CurrencyFundamentals, jsonable
from forex_trader.domain.strategy import SignalFusionPolicy
from forex_trader.infrastructure.repository import SqliteDecisionRepository
from forex_trader.research.backtest import run_walk_forward_backtest

parser = argparse.ArgumentParser()
parser.add_argument("--instrument", default=None)
parser.add_argument("--days", type=int, default=90)
parser.add_argument("--spread-pips", type=Decimal, default=Decimal("1.0"))
parser.add_argument("--technical-only", action="store_true")
args = parser.parse_args()

if args.days < 7:
    raise SystemExit("--days must be at least 7")
config = AppConfig.from_env()
if not config.oanda_token:
    raise SystemExit("OANDA_API_TOKEN is required")
instrument = (args.instrument or config.instruments[0]).upper()
base, quote = instrument.split("_", maxsplit=1)
repo = SqliteDecisionRepository(config.database_path)

if args.technical_only:
    fundamentals: FundamentalBook | PointInTimeFundamentalBook = FundamentalBook(
        [
            CurrencyFundamentals(base, confidence=Decimal("0")),
            CurrencyFundamentals(quote, confidence=Decimal("0")),
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
with OandaPracticeClient(
    token=config.oanda_token,
    account_id=config.oanda_account_id,
    rest_url=config.oanda_rest_url,
    stream_url=config.oanda_stream_url,
    timeout_seconds=config.oanda_timeout_seconds,
) as client:
    lower = client.candles_between(instrument, "M5", start, end)
    higher = client.candles_between(instrument, "H1", start - timedelta(days=10), end)
    client.instrument_spec(instrument)

trades, report = run_walk_forward_backtest(
    instrument=instrument,
    lower_candles=lower,
    higher_candles=higher,
    fundamentals=fundamentals,
    fusion_policy=SignalFusionPolicy(
        minimum_score=config.minimum_score,
        maximum_spread_pips=config.maximum_spread_pips,
        require_fundamentals=not args.technical_only,
    ),
    spread_pips=args.spread_pips,
)
print(json.dumps({
    "scope": "technical-only" if args.technical_only else "point-in-time combined",
    "instrument": instrument,
    "start": start.isoformat(),
    "end": end.isoformat(),
    "report": jsonable(report),
    "evaluated_trades": len(trades),
}, indent=2, sort_keys=True))
