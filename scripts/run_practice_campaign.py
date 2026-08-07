"""Run an evidence-first FX shadow/Practice campaign.

The script never changes strategy thresholds. It can discover OANDA's real currency-pair
universe, caps new submissions per cycle, keeps evaluating remaining instruments in shadow
after the order budget is spent, and writes one JSONL evidence record per cycle.

Before an authenticated campaign, run `forex-trader sync` and the read-only Practice probe.
Never put OANDA credentials on the command line; provide them through the local environment.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from forex_trader.application.campaign import PracticeCampaignRunner
from forex_trader.config import AppConfig, build_engine
from forex_trader.domain.enums import OperatingMode, ProviderKind
from forex_trader.domain.timeframes import granularity_duration


parser = argparse.ArgumentParser()
parser.add_argument("--execute", action="store_true", help="Allow gated Practice submissions")
parser.add_argument(
    "--all-currency-pairs",
    action="store_true",
    help="Use the broker-discovered currency universe instead of FOREX_INSTRUMENTS",
)
parser.add_argument("--max-instruments", type=int, default=None)
parser.add_argument("--max-orders-per-cycle", type=int, default=1)
parser.add_argument("--max-cycles", type=int, default=1)
parser.add_argument(
    "--interval-seconds",
    type=float,
    default=None,
    help="Defaults to one configured lower-timeframe bar",
)
parser.add_argument(
    "--evidence-path",
    type=Path,
    default=Path("campaign-evidence.jsonl"),
)
args = parser.parse_args()

config = AppConfig.from_env()
errors = config.validate()
if errors:
    raise SystemExit("invalid configuration: " + "; ".join(errors))
if args.max_instruments is not None and args.max_instruments < 1:
    raise SystemExit("--max-instruments must be positive")
if args.max_orders_per_cycle < 0:
    raise SystemExit("--max-orders-per-cycle cannot be negative")
if args.max_cycles < 1:
    raise SystemExit("--max-cycles must be positive")
if args.execute:
    if config.provider is not ProviderKind.OANDA:
        raise SystemExit("--execute campaign is reserved for the OANDA Practice provider")
    if config.mode is not OperatingMode.PAPER or not config.enable_paper_orders:
        raise SystemExit(
            "--execute requires FOREX_MODE=paper and FOREX_ENABLE_PAPER_ORDERS=true"
        )

engine = build_engine(config)
if args.all_currency_pairs:
    instruments = engine.instrument_universe()
else:
    instruments = config.instruments
if args.max_instruments is not None:
    instruments = instruments[: args.max_instruments]
if not instruments:
    raise SystemExit("campaign instrument universe is empty")

interval = (
    args.interval_seconds
    if args.interval_seconds is not None
    else granularity_duration(config.lower_timeframe).total_seconds()
)
if interval < 0:
    raise SystemExit("--interval-seconds cannot be negative")

runner = PracticeCampaignRunner(
    engine,
    instruments,
    execute=args.execute,
    max_new_orders_per_cycle=args.max_orders_per_cycle,
    stop_on_unresolved=True,
    evidence_path=args.evidence_path,
)


def emit(report):  # type: ignore[no-untyped-def]
    print(json.dumps(report.to_jsonable(), indent=2, sort_keys=True))


result = runner.run(
    max_cycles=args.max_cycles,
    interval_seconds=interval,
    on_cycle=emit,
)
print(
    json.dumps(
        {
            "campaign_complete": True,
            "mode": "practice-execution" if args.execute else "shadow",
            "provider": config.provider.value,
            "timeframe_policy": {
                "lower": config.lower_timeframe,
                "higher": config.higher_timeframe,
            },
            "instruments": len(instruments),
            "cycles": len(result.cycles),
            "evaluations": result.evaluated,
            "orders_submitted": result.submitted,
            "unknown_orders": result.unknown,
            "unresolved_orders": result.unresolved,
            "evidence_path": str(args.evidence_path),
            "note": (
                "Trade frequency is an observed outcome. The campaign does not lower strategy/risk gates "
                "to manufacture fills. Any unresolved broker state stops further campaign risk."
            ),
        },
        indent=2,
        sort_keys=True,
    )
)
