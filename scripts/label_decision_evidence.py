"""Label matured decision evidence with later OANDA Practice-market candles.

This script is read-only: it requests historical candles and cannot submit or modify broker
orders. It turns point-in-time campaign decisions into conservative outcome evidence for
chronological calibration/EV research. Credentials must be supplied through the environment.
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
from forex_trader.research.dataset import (
    append_outcome_evidence,
    decision_key,
    label_mature_decisions,
    load_outcome_evidence,
)
from forex_trader.research.evidence import load_decision_evidence


parser = argparse.ArgumentParser()
parser.add_argument("decision_evidence", type=Path)
parser.add_argument("--output", type=Path, default=Path("outcome-evidence.jsonl"))
parser.add_argument("--maximum-bars", type=int, default=24)
parser.add_argument("--entry-delay-bars", type=int, default=0)
parser.add_argument("--entry-slippage-pips", type=Decimal, default=Decimal("0.10"))
parser.add_argument("--exit-slippage-pips", type=Decimal, default=Decimal("0.10"))
parser.add_argument("--maximum-pages", type=int, default=200)
args = parser.parse_args()

if args.maximum_bars < 1:
    raise SystemExit("--maximum-bars must be positive")
if args.entry_delay_bars < 0:
    raise SystemExit("--entry-delay-bars cannot be negative")
if args.entry_slippage_pips < 0 or args.exit_slippage_pips < 0:
    raise SystemExit("slippage assumptions cannot be negative")
if args.maximum_pages < 1:
    raise SystemExit("--maximum-pages must be positive")

config = AppConfig.from_env()
if config.provider is not ProviderKind.OANDA:
    raise SystemExit("labeling real campaign evidence requires FOREX_PROVIDER=oanda")
errors = config.validate()
if errors:
    raise SystemExit("invalid configuration: " + "; ".join(errors))
assert config.oanda_token is not None

records = load_decision_evidence(args.decision_evidence)
existing_keys: set[str] = set()
if args.output.exists() and args.output.stat().st_size:
    existing_keys = {row.decision_key for row in load_outcome_evidence(args.output)}

pending = [
    record
    for record in records
    if record.is_trade_candidate
    and record.signal_time is not None
    and decision_key(record) not in existing_keys
]
if not pending:
    print(json.dumps({"labeled": 0, "pending_trade_decisions": 0, "output": str(args.output)}, indent=2))
    raise SystemExit(0)

client = SafeOandaPracticeClient(
    token=config.oanda_token,
    account_id=config.oanda_account_id,
    rest_url=config.oanda_rest_url,
    stream_url=config.oanda_stream_url,
    timeout_seconds=config.oanda_timeout_seconds,
)
now = datetime.now(UTC)
by_instrument: dict[str, list[object]] = defaultdict(list)
for record in pending:
    by_instrument[record.instrument].append(record)

candles_by_instrument = {}
for instrument, instrument_records in sorted(by_instrument.items()):
    signal_times = [record.signal_time for record in instrument_records if record.signal_time is not None]
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

outcomes = label_mature_decisions(
    pending,
    candles_by_instrument,
    maximum_bars=args.maximum_bars,
    spread_from_decision_quote=True,
    entry_slippage_pips=args.entry_slippage_pips,
    exit_slippage_pips=args.exit_slippage_pips,
    entry_delay_bars=args.entry_delay_bars,
    labeled_at=now,
    label_policy=(
        f"ohlc-conservative-v1:{config.lower_timeframe}:bars={args.maximum_bars}:"
        f"entry_delay={args.entry_delay_bars}:entry_slip={args.entry_slippage_pips}:"
        f"exit_slip={args.exit_slippage_pips}:decision_quote_spread=true"
    ),
)
for outcome in outcomes:
    append_outcome_evidence(args.output, outcome)

print(
    json.dumps(
        {
            "read_only": True,
            "provider": "oanda-practice-market-data",
            "decision_records": len(records),
            "pending_trade_decisions": len(pending),
            "labeled": len(outcomes),
            "not_yet_mature_or_missing_candles": len(pending) - len(outcomes),
            "instruments_requested": len(by_instrument),
            "output": str(args.output),
            "labeling_assumptions": {
                "maximum_bars": args.maximum_bars,
                "entry_delay_bars": args.entry_delay_bars,
                "entry_slippage_pips": str(args.entry_slippage_pips),
                "exit_slippage_pips": str(args.exit_slippage_pips),
                "spread": "captured decision quote",
                "same_bar_stop_target": "stop_first_conservative",
            },
        },
        indent=2,
        sort_keys=True,
    )
)
