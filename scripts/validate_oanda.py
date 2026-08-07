"""Multi-instrument rolling validation with one deployable global threshold.

Every pair uses broker instrument metadata, point-in-time fundamentals by default and an
untouched final holdout. Pair-specific thresholds are not promoted because production
uses one global policy unless an explicitly versioned pair policy is later implemented.
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
from forex_trader.infrastructure.trading_repository import TradingRepository
from forex_trader.research.backtest import run_walk_forward_backtest
from forex_trader.research.validation import validate_multiple_instruments

parser = argparse.ArgumentParser()
parser.add_argument("--instruments", default=None, help="Comma-separated OANDA instruments")
parser.add_argument("--days", type=int, default=180)
parser.add_argument("--spread-pips", type=Decimal, default=Decimal("1.0"))
parser.add_argument("--technical-only", action="store_true")
parser.add_argument("--train-size", type=int, default=80)
parser.add_argument("--validation-size", type=int, default=40)
parser.add_argument("--step", type=int, default=40)
args = parser.parse_args()

config = AppConfig.from_env()
if not config.oanda_token:
    raise SystemExit("OANDA_API_TOKEN is required")
instruments = tuple(
    item.strip().upper()
    for item in (args.instruments.split(",") if args.instruments else config.instruments)
    if item.strip()
)
repo = TradingRepository(config.database_path)
observations = repo.macro_observations()
if not args.technical_only and not observations:
    raise SystemExit("point-in-time macro history is empty; import history or use --technical-only")
seeds = load_macro_file(None, use_demo_defaults=False).snapshots()
end = datetime.now(UTC)
start = end - timedelta(days=args.days)
trades_by_instrument = {}
pip_sizes: dict[str, str] = {}
with SafeOandaPracticeClient(
    token=config.oanda_token,
    account_id=config.oanda_account_id,
    rest_url=config.oanda_rest_url,
    stream_url=config.oanda_stream_url,
    timeout_seconds=config.oanda_timeout_seconds,
) as client:
    for instrument in instruments:
        spec = client.instrument_spec(instrument)
        pip_sizes[instrument] = str(spec.pip_size)
        base, quote = instrument.split("_", maxsplit=1)
        if args.technical_only:
            fundamentals: FundamentalBook | PointInTimeFundamentalBook = FundamentalBook([
                CurrencyFundamentals(base, confidence=Decimal("0"), as_of=datetime(2000, 1, 1, tzinfo=UTC)),
                CurrencyFundamentals(quote, confidence=Decimal("0"), as_of=datetime(2000, 1, 1, tzinfo=UTC)),
            ])
        else:
            fundamentals = PointInTimeFundamentalBook(observations, seeds=seeds)
        lower = client.candles_between(instrument, "M5", start, end)
        higher = client.candles_between(instrument, "H1", start - timedelta(days=10), end)
        trades, _ = run_walk_forward_backtest(
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
        )
        trades_by_instrument[instrument] = trades

try:
    report = validate_multiple_instruments(
        trades_by_instrument,
        train_size=args.train_size,
        validation_size=args.validation_size,
        step=args.step,
    )
except ValueError as exc:
    raise SystemExit(f"insufficient history for multi-window validation: {exc}") from exc
print(json.dumps({
    "scope": "technical-only" if args.technical_only else "point-in-time combined",
    "start": start.isoformat(),
    "end": end.isoformat(),
    "pip_sizes": pip_sizes,
    "report": jsonable(report),
    "deployment_policy": "One global threshold is selected on pooled development folds and applied unchanged to every untouched pair holdout.",
    "promotion_note": "Holdout performance is research evidence, not a live-money promotion decision.",
}, indent=2, sort_keys=True))
