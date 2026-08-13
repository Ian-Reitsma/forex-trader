"""Chronological holdout sweep for RuntimeManagementPolicy using read-only OANDA candles."""
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
from forex_trader.domain.technicals import pip_size
from forex_trader.research.evidence import candidate_from_evidence, load_decision_evidence
from forex_trader.research.runtime_management_sweep import (
    chronological_holdout_split,
    default_runtime_management_grid,
    evaluate_sweep_point,
    rank_sweep_results,
)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Read-only chronological holdout sweep of RuntimeManagementPolicy parameters."
    )
    parser.add_argument("decision_evidence", type=Path)
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("diagnostics/runtime-management-sweep.json"),
    )
    parser.add_argument("--exit-slippage-pips", type=Decimal, default=Decimal("0.10"))
    parser.add_argument("--maximum-pages", type=int, default=200)
    parser.add_argument("--train-fraction", type=Decimal, default=Decimal("0.625"))
    parser.add_argument("--top-k", type=int, default=10)
    return parser


def _spread_pips(record) -> Decimal:  # type: ignore[no-untyped-def]
    if record.quote_bid is None or record.quote_ask is None:
        return Decimal("0")
    return max(Decimal("0"), record.quote_ask - record.quote_bid) / pip_size(record.instrument)


def main() -> int:
    args = _parser().parse_args()
    if args.exit_slippage_pips < 0:
        raise SystemExit("exit slippage cannot be negative")
    if args.maximum_pages < 1 or args.top_k < 1:
        raise SystemExit("maximum pages and top-k must be positive")

    config = AppConfig.from_env()
    errors = config.validate()
    if errors:
        raise SystemExit("invalid configuration: " + "; ".join(errors))
    if config.provider is not ProviderKind.OANDA or config.oanda_token is None:
        raise SystemExit("runtime management sweep requires OANDA Practice market-data configuration")

    records = sorted(
        (
            record
            for record in load_decision_evidence(args.decision_evidence)
            if record.is_trade_candidate
            and record.signal_time is not None
            and record.order_status is not None
        ),
        key=lambda record: record.signal_time or datetime.min.replace(tzinfo=UTC),
    )
    if len(records) < 4:
        raise SystemExit("at least four order-bearing trade candidates are required")

    now = datetime.now(UTC)
    by_instrument = defaultdict(list)
    for record in records:
        by_instrument[record.instrument].append(record)

    client = SafeOandaPracticeClient(
        token=config.oanda_token,
        account_id=config.oanda_account_id,
        rest_url=config.oanda_rest_url,
        stream_url=config.oanda_stream_url,
        timeout_seconds=config.oanda_timeout_seconds,
    )
    candles_by_instrument = {}
    for instrument, instrument_records in sorted(by_instrument.items()):
        starts = [record.signal_time for record in instrument_records if record.signal_time is not None]
        candles_by_instrument[instrument] = client.candles_between(
            instrument,
            config.lower_timeframe,
            min(starts),
            now,
            maximum_pages=args.maximum_pages,
        )

    samples = []
    sample_metadata = []
    for record in records:
        assert record.signal_time is not None
        future = tuple(
            candle
            for candle in candles_by_instrument.get(record.instrument, ())
            if candle.time >= record.signal_time
        )
        if not future:
            continue
        samples.append((candidate_from_evidence(record), future, _spread_pips(record)))
        sample_metadata.append(
            {
                "candidate_id": record.candidate_id,
                "instrument": record.instrument,
                "signal_time": record.signal_time.isoformat(),
            }
        )
    if len(samples) < 4:
        raise SystemExit("fewer than four candidates have usable future candle paths")

    indexed = tuple(zip(samples, sample_metadata, strict=True))
    train_indexed, holdout_indexed = chronological_holdout_split(
        indexed,
        train_fraction=args.train_fraction,
    )
    train_samples = tuple(item[0] for item in train_indexed)
    holdout_samples = tuple(item[0] for item in holdout_indexed)

    train_results = rank_sweep_results(
        evaluate_sweep_point(
            point,
            train_samples,
            exit_slippage_pips=args.exit_slippage_pips,
        )
        for point in default_runtime_management_grid()
    )
    finalists = train_results[: min(args.top_k, len(train_results))]
    holdout_results = []
    for train_row in finalists:
        policy_payload = train_row["policy"]
        point = next(
            point
            for point in default_runtime_management_grid()
            if point.to_jsonable() == policy_payload
        )
        holdout_row = evaluate_sweep_point(
            point,
            holdout_samples,
            exit_slippage_pips=args.exit_slippage_pips,
        )
        holdout_results.append(
            {
                "policy": policy_payload,
                "train": train_row,
                "holdout": holdout_row,
            }
        )

    holdout_ranked = sorted(
        holdout_results,
        key=lambda row: (
            Decimal(str(row["holdout"]["expectancy_r"])),
            Decimal(str(row["holdout"]["total_r"])),
            -Decimal(str(row["holdout"]["max_drawdown_r"])),
        ),
        reverse=True,
    )

    default_policy = next(
        point
        for point in default_runtime_management_grid()
        if point.progress_check_minutes == 30
        and point.minimum_progress_r == Decimal("0.15")
        and point.maximum_holding_minutes == 120
        and point.break_even_after_r == Decimal("1.00")
    )
    default_train = evaluate_sweep_point(
        default_policy,
        train_samples,
        exit_slippage_pips=args.exit_slippage_pips,
    )
    default_holdout = evaluate_sweep_point(
        default_policy,
        holdout_samples,
        exit_slippage_pips=args.exit_slippage_pips,
    )

    payload = {
        "schema": "runtime-management-sweep-v1",
        "research_only": True,
        "broker_write_authority": False,
        "generated_at": now.isoformat(),
        "sample_count": len(samples),
        "train_count": len(train_samples),
        "holdout_count": len(holdout_samples),
        "train_fraction": str(args.train_fraction),
        "grid_points": len(default_runtime_management_grid()),
        "selection_rule": "rank on chronological train expectancy/total-R/drawdown; evaluate only top-k on untouched chronological holdout",
        "warning": "small-sample research only; no parameter set authorizes broker writes or larger position sizing",
        "samples": sample_metadata,
        "default_policy": {
            "train": default_train,
            "holdout": default_holdout,
        },
        "top_train_policies": list(finalists),
        "holdout_ranked_finalists": holdout_ranked,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(
        json.dumps(
            {
                "output": str(args.output.resolve()),
                "sample_count": len(samples),
                "train_count": len(train_samples),
                "holdout_count": len(holdout_samples),
                "grid_points": len(default_runtime_management_grid()),
                "top_holdout": holdout_ranked[0] if holdout_ranked else None,
            },
            indent=2,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
