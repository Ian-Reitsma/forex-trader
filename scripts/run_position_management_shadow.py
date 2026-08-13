"""Compare static brackets with RuntimeManagementPolicy using read-only OANDA candles."""
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
from forex_trader.domain.position_management import RuntimeManagementPolicy
from forex_trader.domain.technicals import pip_size
from forex_trader.research.backtest import evaluate_candidate_outcome, summarize_trades
from forex_trader.research.evidence import candidate_from_evidence, load_decision_evidence
from forex_trader.research.runtime_management_shadow import evaluate_runtime_management_shadow


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Read-only counterfactual of current runtime position-management policy.")
    parser.add_argument("decision_evidence", type=Path)
    parser.add_argument("--output", type=Path, default=Path("diagnostics/position-management-shadow.json"))
    parser.add_argument("--all-candidates", action="store_true", help="Default scope is candidates whose captured trace had an order status.")
    parser.add_argument("--baseline-bars", type=int, default=576, help="Static bracket observation horizon; 576 M5 bars = 48 hours.")
    parser.add_argument("--exit-slippage-pips", type=Decimal, default=Decimal("0.10"))
    parser.add_argument("--maximum-pages", type=int, default=200)
    return parser


def _spread_pips(record) -> Decimal:  # type: ignore[no-untyped-def]
    if record.quote_bid is None or record.quote_ask is None:
        return Decimal("0")
    return max(Decimal("0"), record.quote_ask - record.quote_bid) / pip_size(record.instrument)


def _report_summary(trades) -> dict[str, object]:  # type: ignore[no-untyped-def]
    report = summarize_trades(list(trades))
    return {
        "trades": report.trades,
        "wins": report.wins,
        "losses": report.losses,
        "timeouts": report.timeouts,
        "win_rate": str(report.win_rate),
        "expectancy_r": str(report.expectancy_r),
        "total_r": str(report.total_r),
        "max_drawdown_r": str(report.max_drawdown_r),
        "average_mfe_r": str(report.average_mfe_r),
        "average_mae_r": str(report.average_mae_r),
        "average_cost_r": str(report.average_cost_r),
    }


def main() -> int:
    args = _parser().parse_args()
    if args.baseline_bars < 1 or args.maximum_pages < 1:
        raise SystemExit("baseline bars and maximum pages must be positive")
    if args.exit_slippage_pips < 0:
        raise SystemExit("exit slippage cannot be negative")

    config = AppConfig.from_env()
    errors = config.validate()
    if errors:
        raise SystemExit("invalid configuration: " + "; ".join(errors))
    if config.provider is not ProviderKind.OANDA or config.oanda_token is None:
        raise SystemExit("position-management shadow requires OANDA Practice market-data configuration")

    records = load_decision_evidence(args.decision_evidence)
    candidates = [
        record
        for record in records
        if record.is_trade_candidate
        and record.signal_time is not None
        and (args.all_candidates or record.order_status is not None)
    ]
    if not candidates:
        raise SystemExit("no matching trade candidates found")

    now = datetime.now(UTC)
    by_instrument = defaultdict(list)
    for record in candidates:
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

    policy = RuntimeManagementPolicy()
    rows = []
    baseline_trades = []
    managed_trades = []
    for record in candidates:
        assert record.signal_time is not None
        future = [candle for candle in candles_by_instrument.get(record.instrument, []) if candle.time >= record.signal_time]
        if not future:
            continue
        candidate = candidate_from_evidence(record)
        spread = _spread_pips(record)
        baseline = evaluate_candidate_outcome(
            candidate,
            future,
            maximum_bars=args.baseline_bars,
            spread_pips=spread,
            exit_slippage_pips=args.exit_slippage_pips,
        )
        managed = evaluate_runtime_management_shadow(
            candidate,
            future,
            policy,
            spread_pips=spread,
            exit_slippage_pips=args.exit_slippage_pips,
        )
        baseline_trades.append(baseline)
        managed_trades.append(managed)
        rows.append(
            {
                "candidate_id": record.candidate_id,
                "instrument": record.instrument,
                "signal_time": record.signal_time.isoformat(),
                "risk_disposition": record.risk_disposition,
                "order_status": record.order_status,
                "static": {
                    "status": baseline.status.value,
                    "r": str(baseline.r_multiple),
                    "bars": baseline.bars_held,
                    "exit_reason": baseline.exit_reason,
                },
                "runtime_management_shadow": {
                    "status": managed.status.value,
                    "r": str(managed.r_multiple),
                    "bars": managed.bars_held,
                    "exit_reason": managed.exit_reason,
                },
                "delta_r": str(managed.r_multiple - baseline.r_multiple),
            }
        )

    payload = {
        "schema": "position-management-shadow-v1",
        "research_only": True,
        "broker_write_authority": False,
        "generated_at": now.isoformat(),
        "scope": "all trade candidates" if args.all_candidates else "candidates with captured order status",
        "policy": {
            "maximum_holding_minutes": int(policy.maximum_holding_time.total_seconds() // 60),
            "progress_check_minutes": int(policy.progress_check_after.total_seconds() // 60),
            "minimum_progress_r": str(policy.minimum_progress_r),
            "break_even_after_r": str(policy.break_even_after_r),
        },
        "assumptions": {
            "timeframe": config.lower_timeframe,
            "baseline_bars": args.baseline_bars,
            "spread": "captured decision quote held constant",
            "exit_slippage_pips": str(args.exit_slippage_pips),
            "events": "not invented; event-management branches are not evaluated without point-in-time event evidence",
            "structure_invalidation": "not invented",
        },
        "static_summary": _report_summary(baseline_trades),
        "runtime_management_summary": _report_summary(managed_trades),
        "total_delta_r": str(sum((row.r_multiple for row in managed_trades), Decimal("0")) - sum((row.r_multiple for row in baseline_trades), Decimal("0"))),
        "trades": rows,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({"output": str(args.output.resolve()), "trades": len(rows), "total_delta_r": payload["total_delta_r"]}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
