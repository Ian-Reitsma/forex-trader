"""Mature prospective paired-ablation decisions with read-only OANDA Practice candles.

The script cannot submit, modify or close broker orders. It labels complete six-variant
snapshot groups atomically using the same conservative OHLC outcome engine as ordinary
decision evidence. Abstentions/evaluator failures remain in the paired denominator at 0R.
"""
from __future__ import annotations

import argparse
import json
from collections import defaultdict
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

from forex_trader.adapters.oanda_safe import SafeOandaPracticeClient
from forex_trader.config import AppConfig
from forex_trader.domain.enums import ProviderKind
from forex_trader.research.ablation_maturity import completed_snapshot_ids, mature_ablation_outcomes
from forex_trader.research.ablations import (
    append_matured_ablation_outcomes,
    load_ablation_decisions,
    load_matured_ablation_outcomes,
)


parser = argparse.ArgumentParser()
parser.add_argument("ablation_decisions", type=Path)
parser.add_argument("--output", type=Path, default=Path("matured-ablation-outcomes.jsonl"))
parser.add_argument("--maximum-bars", type=int, default=24)
parser.add_argument("--entry-delay-bars", type=int, default=0)
parser.add_argument("--entry-slippage-pips", type=Decimal, default=Decimal("0.10"))
parser.add_argument("--exit-slippage-pips", type=Decimal, default=Decimal("0.10"))
parser.add_argument("--maximum-pages", type=int, default=200)
args = parser.parse_args()

if args.maximum_bars < 1:
    raise SystemExit("--maximum-bars must be positive")
if args.entry_delay_bars < 0 or args.entry_delay_bars >= args.maximum_bars:
    raise SystemExit("--entry-delay-bars must be in [0, maximum-bars)")
if args.entry_slippage_pips < 0 or args.exit_slippage_pips < 0:
    raise SystemExit("slippage assumptions cannot be negative")
if args.maximum_pages < 1:
    raise SystemExit("--maximum-pages must be positive")

records = load_ablation_decisions(args.ablation_decisions, require_complete=True)
existing_ids: frozenset[str] = frozenset()
if args.output.exists() and args.output.stat().st_size:
    existing_ids = completed_snapshot_ids(load_matured_ablation_outcomes(args.output))

pending = tuple(row for row in records if row.snapshot_id not in existing_ids)
pending_snapshot_ids = {row.snapshot_id for row in pending}
if not pending:
    print(
        json.dumps(
            {
                "read_only": True,
                "labeled_snapshots": 0,
                "labeled_rows": 0,
                "pending_snapshots": 0,
                "output": str(args.output),
            },
            indent=2,
            sort_keys=True,
        )
    )
    raise SystemExit(0)

config = AppConfig.from_env()
if config.provider is not ProviderKind.OANDA:
    raise SystemExit("labeling real ablation evidence requires FOREX_PROVIDER=oanda")
errors = config.validate()
if errors:
    raise SystemExit("invalid configuration: " + "; ".join(errors))
assert config.oanda_token is not None

client = SafeOandaPracticeClient(
    token=config.oanda_token,
    account_id=config.oanda_account_id,
    rest_url=config.oanda_rest_url,
    stream_url=config.oanda_stream_url,
    timeout_seconds=config.oanda_timeout_seconds,
)
now = datetime.now(UTC)
tradeable_by_instrument: dict[str, list[object]] = defaultdict(list)
for row in pending:
    if row.tradeable:
        tradeable_by_instrument[row.instrument].append(row)

candles_by_instrument = {}
for instrument, instrument_records in sorted(tradeable_by_instrument.items()):
    signal_times = [row.signal_time for row in instrument_records]
    if not signal_times:
        continue
    start = min(signal_times)
    if start >= now:
        continue
    candles_by_instrument[instrument] = client.candles_between(
        instrument,
        config.lower_timeframe,
        start,
        now,
        maximum_pages=args.maximum_pages,
    )

label_policy = (
    f"ohlc-conservative-ablation-v1:{config.lower_timeframe}:bars={args.maximum_bars}:"
    f"entry_delay={args.entry_delay_bars}:entry_slip={args.entry_slippage_pips}:"
    f"exit_slip={args.exit_slippage_pips}:captured_quote_spread=true:atomic_pairs=true"
)
outcomes = mature_ablation_outcomes(
    pending,
    candles_by_instrument,
    maximum_bars=args.maximum_bars,
    entry_slippage_pips=args.entry_slippage_pips,
    exit_slippage_pips=args.exit_slippage_pips,
    entry_delay_bars=args.entry_delay_bars,
    labeled_at=now,
    label_policy=label_policy,
)
append_matured_ablation_outcomes(args.output, outcomes)
matured_ids = {row.snapshot_id for row in outcomes}

print(
    json.dumps(
        {
            "read_only": True,
            "provider": "oanda-practice-market-data",
            "prospective_rows": len(records),
            "pending_snapshots": len(pending_snapshot_ids),
            "labeled_snapshots": len(matured_ids),
            "labeled_rows": len(outcomes),
            "not_yet_mature_snapshots": len(pending_snapshot_ids - matured_ids),
            "tradeable_instruments_requested": len(tradeable_by_instrument),
            "output": str(args.output),
            "labeling_assumptions": {
                "maximum_bars": args.maximum_bars,
                "entry_delay_bars": args.entry_delay_bars,
                "entry_slippage_pips": str(args.entry_slippage_pips),
                "exit_slippage_pips": str(args.exit_slippage_pips),
                "spread": "captured prospective decision quote",
                "same_bar_stop_target": "stop_first_conservative",
                "nontradeable_variant_return": "0R",
                "snapshot_write_policy": "all_six_variants_atomic",
            },
        },
        indent=2,
        sort_keys=True,
    )
)
