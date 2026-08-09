from __future__ import annotations

import argparse
import asyncio
import json
import os
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any

from forex_trader.domain.macro_history import PointInTimeFundamentalBook
from forex_trader.domain.models import jsonable
from forex_trader.ingestion.file_providers import JsonEconomicCalendarProvider
from forex_trader.research.portfolio_risk_replay import HistoricalPortfolioRiskConfig
from forex_trader.research.public_history import HistoricalTick, utc_range
from forex_trader.research.release_surprise_history import PointInTimeReleaseSurpriseAssembler
from forex_trader.research.resilient_tick_history import ResilientDukascopyHistoryClient
from forex_trader.research.staged_historical_development import (
    DEFAULT_RISK_FRACTION,
    MACRO_MINIMUM_CONFIDENCE,
    MACRO_MINIMUM_DIRECTIONAL_SUPPORT,
    STRUCTURED_ZONE_MAXIMUM_DISTANCE_ATR,
    STRUCTURED_ZONE_MINIMUM_QUALITY,
    FlowHistory,
    SpotHistoryIndex,
    evaluate_stages,
    generate_causal_executions,
    load_normalized_order_flow,
    replay_production_portfolio_risk,
    stage_metrics,
)


def _existing_path(explicit: str | None, env_name: str) -> Path | None:
    raw = explicit or os.getenv(env_name)
    if not raw:
        return None
    path = Path(raw)
    if not path.exists():
        raise FileNotFoundError(f"{env_name} path does not exist: {path}")
    return path


def _macro_book(
    path: Path | None,
    *,
    history_start: datetime,
    end: datetime,
) -> tuple[PointInTimeFundamentalBook | None, dict[str, object]]:
    if path is None:
        return None, {
            "status": "unavailable",
            "reason": "no normalized real point-in-time economic-calendar/consensus archive supplied",
            "records": 0,
            "unmatched_actuals": 0,
        }
    provider = JsonEconomicCalendarProvider(path)
    metadata = provider.release_metadata()
    consensus = provider.consensus_snapshots(start=history_start, end=end)
    actuals = provider.release_actuals(start=history_start, end=end)
    assembled = PointInTimeReleaseSurpriseAssembler(metadata, consensus, actuals).assemble()
    observations = assembled.macro_observations()
    return PointInTimeFundamentalBook(observations), {
        "status": "available" if observations else "unavailable",
        "source": str(path),
        "metadata": len(metadata),
        "consensus_snapshots": len(consensus),
        "actual_releases": len(actuals),
        "records": len(assembled.records),
        "unmatched_actuals": len(assembled.unmatched_actuals),
        "complete": assembled.complete,
        "unmatched_examples": [
            {
                "currency": item.actual.currency,
                "indicator": item.actual.indicator,
                "available_at": item.actual.available_at,
                "reason": item.reason,
            }
            for item in assembled.unmatched_actuals[:10]
        ],
    }


def _flow_history(path: Path | None) -> tuple[FlowHistory | None, dict[str, object]]:
    if path is None:
        return None, {
            "status": "unavailable",
            "reason": "no normalized real centralized futures/order-flow archive supplied",
            "snapshots": 0,
        }
    snapshots = load_normalized_order_flow(path)
    centralized = tuple(item for item in snapshots if item.source.strip().lower() not in {"", "none", "broker_tick_proxy"})
    if not centralized:
        return None, {
            "status": "unavailable",
            "source": str(path),
            "reason": "order-flow archive contained no eligible centralized source snapshots",
            "snapshots": len(snapshots),
            "centralized_snapshots": 0,
        }
    return FlowHistory.from_snapshots(centralized), {
        "status": "available",
        "source": str(path),
        "snapshots": len(snapshots),
        "centralized_snapshots": len(centralized),
        "sources": sorted({item.source for item in centralized}),
    }


def _risk_selected_ids(report: object) -> set[object]:
    admitted = getattr(report, "admitted_opportunities")
    return {item.candidate.candidate_id for item in admitted}


async def run(args: argparse.Namespace) -> dict[str, object]:
    start_date = date.fromisoformat(args.start)
    end_date = date.fromisoformat(args.end)
    start, end = utc_range(start_date, end_date)
    if end <= start:
        raise ValueError("development end must be after start")
    instruments = tuple(item.strip().upper() for item in args.instruments.split(",") if item.strip())
    if not instruments:
        raise ValueError("at least one instrument is required")
    history_start = start - timedelta(days=args.warmup_days)
    cache_dir = Path(args.cache_dir)
    cache_dir.mkdir(parents=True, exist_ok=True)

    ticks_by_instrument: dict[str, tuple[HistoricalTick, ...]] = {}
    executions = []
    empty_fundamentals = PointInTimeFundamentalBook()
    per_instrument: dict[str, object] = {}
    for instrument in instruments:
        history = ResilientDukascopyHistoryClient(
            cache_dir=cache_dir / "dukascopy",
            max_concurrency=args.concurrency_per_pair,
        )
        ticks = await history.ticks(instrument, history_start, end)
        ticks_by_instrument[instrument] = ticks
        generated = generate_causal_executions(
            instrument=instrument,
            ticks=ticks,
            fundamentals=empty_fundamentals,
            maximum_holding=timedelta(minutes=args.maximum_holding_minutes),
            entry_latency=timedelta(milliseconds=args.entry_latency_ms),
            adverse_slippage_pips=Decimal(args.slippage_pips),
            decision_start=start,
            decision_end=end,
        )
        executions.extend(generated)
        per_instrument[instrument] = {
            "history_ticks_including_warmup": len(ticks),
            "generated_causal_executions": len(generated),
        }

    spot = SpotHistoryIndex.from_ticks(ticks_by_instrument)
    economic_path = _existing_path(args.economic_calendar_path, "FOREX_ECONOMIC_CALENDAR_PATH")
    order_flow_path = _existing_path(args.order_flow_path, "FOREX_ORDER_FLOW_PATH")
    macro_book, macro_source = _macro_book(economic_path, history_start=history_start, end=end)
    flow_history, flow_source = _flow_history(order_flow_path)

    staged = evaluate_stages(
        executions,
        period_start=start,
        period_end=end,
        macro_book=macro_book,
        flow_history=flow_history,
        spot_price_at=spot.price_at,
    )

    if staged.flow_metrics.status == "available":
        risk_input_stage = "centralized_flow"
        risk_input = staged.flow
    elif staged.macro_metrics.status == "available":
        risk_input_stage = "pit_macro_surprise"
        risk_input = staged.macro
    elif staged.structured_zone:
        risk_input_stage = "structured_zone"
        risk_input = staged.structured_zone
    else:
        risk_input_stage = "legacy_technical"
        risk_input = staged.baseline

    risk_config = HistoricalPortfolioRiskConfig(
        starting_balance=Decimal(args.starting_balance),
        risk_fraction=Decimal(args.risk_fraction),
    )
    risk_report = replay_production_portfolio_risk(risk_input, spot_history=spot, config=risk_config)
    admitted_ids = _risk_selected_ids(risk_report)
    risk_selected = tuple(item for item in risk_input if item.candidate.candidate_id in admitted_ids)
    risk_metrics = stage_metrics(
        risk_selected,
        input_count=len(risk_input),
        period_start=start,
        period_end=end,
    )

    strict_pipeline = ["legacy_technical", "structured_zone"]
    if staged.macro_metrics.status == "available":
        strict_pipeline.append("pit_macro_surprise")
        if staged.flow_metrics.status == "available":
            strict_pipeline.append("centralized_flow")
    strict_pipeline_complete = staged.macro_metrics.status == "available" and staged.flow_metrics.status == "available"

    return {
        "schema_version": "staged-historical-development-v1",
        "research_role": "development-only component ablation; no validation/proof claim",
        "period": {
            "development_start": start,
            "development_end_exclusive": end,
            "price_warmup_start": history_start,
            "reserved_future_validation": "NOT_OPENED_BY_THIS_RUN",
        },
        "instruments": instruments,
        "frozen_before_outcomes": {
            "structured_zone_minimum_quality": STRUCTURED_ZONE_MINIMUM_QUALITY,
            "structured_zone_maximum_distance_atr": STRUCTURED_ZONE_MAXIMUM_DISTANCE_ATR,
            "macro_minimum_confidence": MACRO_MINIMUM_CONFIDENCE,
            "macro_minimum_directional_support": MACRO_MINIMUM_DIRECTIONAL_SUPPORT,
            "flow_confirmation": "existing InstitutionalFlowAssessment.eligible_for_confirmation plus direction match",
            "risk_fraction": Decimal(args.risk_fraction),
            "starting_balance": Decimal(args.starting_balance),
        },
        "execution_assumptions": {
            "price_source": "Dukascopy first-party BI5 historical best bid/ask",
            "feature_bars": "M5/H1 midpoint bars derived from the same PIT tick archive",
            "entry_latency_ms": args.entry_latency_ms,
            "adverse_slippage_pips_each_side": args.slippage_pips,
            "maximum_holding_minutes": args.maximum_holding_minutes,
            "same_causal_executions_across_component_filters": True,
            "broker_tick_proxy_allowed_as_institutional_flow": False,
        },
        "per_instrument": per_instrument,
        "external_data": {
            "pit_macro": macro_source,
            "centralized_flow": flow_source,
        },
        "stages": {
            "legacy_technical": jsonable(staged.baseline_metrics),
            "structured_zone": jsonable(staged.structured_zone_metrics),
            "pit_macro_surprise": jsonable(staged.macro_metrics),
            "centralized_flow": jsonable(staged.flow_metrics),
            "production_portfolio_risk": {
                "input_stage": risk_input_stage,
                "metrics": jsonable(risk_metrics),
                "risk_report": jsonable(risk_report),
            },
        },
        "strict_pipeline": {
            "completed_components": strict_pipeline,
            "complete_through_real_flow": strict_pipeline_complete,
            "stopped_reason": "" if strict_pipeline_complete else (
                "missing real PIT macro archive" if staged.macro_metrics.status != "available" else "missing real centralized flow archive"
            ),
        },
        "coverage_counts": {
            "raw_generated": len(executions),
            "legacy_nonoverlap": len(staged.baseline),
            "structured_zone": len(staged.structured_zone),
            "macro": len(staged.macro),
            "flow": len(staged.flow),
            "risk_input": len(risk_input),
            "risk_admitted": len(risk_selected),
        },
        "notes": [
            "April-May 2026 sealed tape is not read or used by this development run.",
            "May-August 2026 prior development tape is not used for threshold selection in this run.",
            "Missing consensus or centralized-flow data fails closed and is reported as unavailable; no proxy substitution is allowed.",
            "The portfolio-risk stage calls the production EnhancedRiskPolicy with causal account/open-position state and H1 correlation history.",
        ],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Run frozen staged Forex Scalper component ablation on real historical FX ticks.")
    parser.add_argument("--instruments", default="EUR_USD,GBP_USD,USD_JPY")
    parser.add_argument("--start", default="2026-01-05")
    parser.add_argument("--end", default="2026-04-01")
    parser.add_argument("--warmup-days", type=int, default=14)
    parser.add_argument("--cache-dir", default=".cache/forex-trader/public-history")
    parser.add_argument("--economic-calendar-path")
    parser.add_argument("--order-flow-path")
    parser.add_argument("--concurrency-per-pair", type=int, default=12)
    parser.add_argument("--maximum-holding-minutes", type=int, default=120)
    parser.add_argument("--entry-latency-ms", type=int, default=500)
    parser.add_argument("--slippage-pips", default="0.10")
    parser.add_argument("--starting-balance", default="100000")
    parser.add_argument("--risk-fraction", default=str(DEFAULT_RISK_FRACTION))
    parser.add_argument("--output", default="artifacts/staged-historical-development-v1.json")
    args = parser.parse_args()
    if args.warmup_days < 7:
        raise SystemExit("--warmup-days must be at least 7")
    if args.maximum_holding_minutes <= 0 or args.entry_latency_ms < 0 or Decimal(args.slippage_pips) < 0:
        raise SystemExit("holding time must be positive; latency/slippage cannot be negative")
    report = asyncio.run(run(args))
    rendered = json.dumps(jsonable(report), indent=2, sort_keys=True)
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(rendered + "\n", encoding="utf-8")
    print(rendered)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
