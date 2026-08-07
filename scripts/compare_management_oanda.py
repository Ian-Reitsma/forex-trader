"""Compare research-only trade-management policies on OANDA Practice history.

This command never places or modifies broker orders. It uses the same configured
lower/higher timeframe policy and point-in-time candidate construction as the runtime
research path, then replays each management policy sequentially so holding periods affect
which later same-instrument signals are eligible.
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
from forex_trader.research.management import HALF_AT_ONE_R_RUNNER, STRUCTURAL_SINGLE_TARGET
from forex_trader.research.management_walk_forward import compare_walk_forward_management_policies

parser = argparse.ArgumentParser()
parser.add_argument("--instrument", default=None)
parser.add_argument("--days", type=int, default=180)
parser.add_argument("--spread-pips", type=Decimal, default=Decimal("1.0"))
parser.add_argument("--exit-slippage-pips", type=Decimal, default=Decimal("0.25"))
parser.add_argument("--technical-only", action="store_true")
args = parser.parse_args()

if args.days < 7:
    raise SystemExit("--days must be at least 7")
if args.spread_pips < 0 or args.exit_slippage_pips < 0:
    raise SystemExit("spread and slippage must be non-negative")

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
    observations = repo.macro_observations()
    if not observations:
        raise SystemExit(
            "point-in-time macro history is empty; import history or use --technical-only"
        )
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

reports = compare_walk_forward_management_policies(
    instrument=instrument,
    lower_candles=lower,
    higher_candles=higher,
    fundamentals=fundamentals,
    fusion_policy=SignalFusionPolicy(
        minimum_score=config.minimum_score,
        maximum_spread_pips=config.maximum_spread_pips,
        require_fundamentals=not args.technical_only,
    ),
    policies=(STRUCTURAL_SINGLE_TARGET, HALF_AT_ONE_R_RUNNER),
    spread_pips=args.spread_pips,
    exit_slippage_pips=args.exit_slippage_pips,
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
            "spread_pips": str(args.spread_pips),
            "exit_slippage_pips": str(args.exit_slippage_pips),
            "reports": [jsonable(report) for report in reports],
            "policy_notes": {
                STRUCTURAL_SINGLE_TARGET.name: "Current runtime baseline: full position to independently derived structural target or stop.",
                HALF_AT_ONE_R_RUNNER.name: "Research hypothesis only: realize 50% at +1R, move remaining stop to breakeven, run remainder to the original structural target.",
            },
            "adoption_rule": (
                "Do not change runtime management from this result alone. The runner policy must "
                "improve untouched after-cost expectancy and/or drawdown across multiple pairs, "
                "time windows and execution stresses before receiving production authority."
            ),
            "historical_price_limitation": (
                "OANDA midpoint candles cannot reveal exact bid/ask intrabar ordering. Ambiguous "
                "paths are treated conservatively and modeled costs are not real historical depth."
            ),
        },
        indent=2,
        sort_keys=True,
    )
)
