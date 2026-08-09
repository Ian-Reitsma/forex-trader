from __future__ import annotations

import argparse
import asyncio
import json
import math
from collections import Counter
from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path
from statistics import median
from typing import Sequence

from forex_trader.domain.macro_history import PointInTimeFundamentalBook
from forex_trader.domain.models import jsonable
from forex_trader.research.backtest import summarize_trades
from forex_trader.research.portfolio_risk_replay import HistoricalPortfolioRiskConfig
from forex_trader.research.public_history import HistoricalTick, utc_range
from forex_trader.research.resilient_tick_history import ResilientDukascopyHistoryClient
from forex_trader.research.return_reporting import simulate_period_returns
from scripts.run_staged_historical_development import (
    CausalExecution,
    SpotHistoryIndex,
    enforce_nonoverlap,
    generate_causal_executions,
    replay_production_portfolio_risk,
)

QUALITY_GRID = (Decimal("0"), Decimal("0.25"), Decimal("0.50"), Decimal("0.75"))
DISTANCE_GRID = (
    Decimal("0.50"),
    Decimal("1.00"),
    Decimal("2.00"),
    Decimal("3.00"),
    Decimal("5.00"),
    Decimal("10.00"),
)
SELECTED_MINIMUM_QUALITY = Decimal("0.75")
SELECTED_MAXIMUM_DISTANCE_ATR = Decimal("5.00")
SELECTED_RISK_FRACTION = Decimal("0.0015")
SELECTED_STARTING_BALANCE = Decimal("100000")


def _quantiles(values: list[Decimal]) -> dict[str, Decimal] | None:
    if not values:
        return None
    ordered = sorted(values)

    def pick(fraction: Decimal) -> Decimal:
        index = int((Decimal(len(ordered) - 1) * fraction).to_integral_value(rounding="ROUND_HALF_UP"))
        return ordered[index]

    return {
        "minimum": ordered[0],
        "p10": pick(Decimal("0.10")),
        "p25": pick(Decimal("0.25")),
        "median": Decimal(str(median(ordered))),
        "p75": pick(Decimal("0.75")),
        "p90": pick(Decimal("0.90")),
        "maximum": ordered[-1],
    }


def _report(values: Sequence[CausalExecution]) -> dict[str, object]:
    report = summarize_trades([item.opportunity.trade for item in values])
    return {
        "trades": report.trades,
        "wins": report.wins,
        "losses": report.losses,
        "timeouts": report.timeouts,
        "win_rate": report.win_rate,
        "expectancy_r": report.expectancy_r,
        "profit_factor": report.profit_factor,
        "total_r": report.total_r,
        "max_drawdown_r": report.max_drawdown_r,
    }


def _uncertainty(values: Sequence[CausalExecution]) -> dict[str, object]:
    if len(values) < 2:
        return {
            "samples": len(values),
            "standard_error_r": None,
            "normal_approx_one_sided_95pct_lcb_r": None,
        }
    returns = [item.opportunity.trade.r_multiple for item in values]
    mean = sum(returns, Decimal("0")) / Decimal(len(returns))
    variance = sum(((value - mean) ** 2 for value in returns), Decimal("0")) / Decimal(len(returns) - 1)
    standard_error = Decimal(str(math.sqrt(float(variance) / len(returns))))
    return {
        "samples": len(values),
        "standard_error_r": standard_error,
        "normal_approx_one_sided_95pct_lcb_r": mean - Decimal("1.645") * standard_error,
    }


def _group_reports(values: Sequence[CausalExecution], key_name: str) -> dict[str, object]:
    grouped: dict[str, list[CausalExecution]] = {}
    for item in values:
        if key_name == "instrument":
            key = item.opportunity.instrument
        elif key_name == "month":
            key = item.opportunity.decision_time.strftime("%Y-%m")
        elif key_name == "direction":
            key = item.candidate.direction.value
        elif key_name == "pattern":
            key = item.structured_zone.pattern or "unknown"
        else:
            raise ValueError(f"unsupported grouping: {key_name}")
        grouped.setdefault(key, []).append(item)
    return {
        key: {"report": _report(group), "uncertainty": _uncertainty(group)}
        for key, group in sorted(grouped.items())
    }


def _selected(values: Sequence[CausalExecution]) -> tuple[CausalExecution, ...]:
    return tuple(
        item
        for item in values
        if item.structured_zone.available
        and item.structured_zone.quality >= SELECTED_MINIMUM_QUALITY
        and item.structured_zone.distance_atr is not None
        and item.structured_zone.distance_atr <= SELECTED_MAXIMUM_DISTANCE_ATR
    )


async def run(args: argparse.Namespace) -> dict[str, object]:
    start, end = utc_range(date.fromisoformat(args.start), date.fromisoformat(args.end))
    history_start = start - timedelta(days=args.warmup_days)
    instruments = tuple(item.strip().upper() for item in args.instruments.split(",") if item.strip())
    fundamentals = PointInTimeFundamentalBook()
    raw: list[CausalExecution] = []
    per_instrument: dict[str, object] = {}
    ticks_by_instrument: dict[str, Sequence[HistoricalTick]] = {}
    for instrument in instruments:
        history = ResilientDukascopyHistoryClient(
            cache_dir=Path(args.cache_dir) / "dukascopy",
            max_concurrency=args.concurrency_per_pair,
        )
        ticks = await history.ticks(instrument, history_start, end)
        ticks_by_instrument[instrument] = ticks
        values = generate_causal_executions(
            instrument=instrument,
            ticks=ticks,
            fundamentals=fundamentals,
            maximum_holding=timedelta(minutes=args.maximum_holding_minutes),
            entry_latency=timedelta(milliseconds=args.entry_latency_ms),
            adverse_slippage_pips=Decimal(args.slippage_pips),
            decision_start=start,
            decision_end=end,
        )
        raw.extend(values)
        per_instrument[instrument] = {"ticks": len(ticks), "raw_executions": len(values)}

    baseline = enforce_nonoverlap(raw)
    available = [item for item in baseline if item.structured_zone.available]
    unavailable = [item for item in baseline if not item.structured_zone.available]
    quality_values = [item.structured_zone.quality for item in available]
    distance_values = [
        item.structured_zone.distance_atr
        for item in available
        if item.structured_zone.distance_atr is not None
    ]
    patterns = Counter(item.structured_zone.pattern or "unknown" for item in available)

    grid: list[dict[str, object]] = []
    for quality in QUALITY_GRID:
        for distance in DISTANCE_GRID:
            grid_selected = [
                item
                for item in available
                if item.structured_zone.quality >= quality
                and item.structured_zone.distance_atr is not None
                and item.structured_zone.distance_atr <= distance
            ]
            grid.append(
                {
                    "minimum_quality": quality,
                    "maximum_distance_atr": distance,
                    "coverage": Decimal(len(grid_selected)) / Decimal(len(baseline)) if baseline else Decimal("0"),
                    "report": _report(grid_selected),
                }
            )

    pattern_reports = {
        pattern: _report([item for item in available if (item.structured_zone.pattern or "unknown") == pattern])
        for pattern in sorted(patterns)
    }
    selected = _selected(baseline)
    spot_history = SpotHistoryIndex.from_ticks(ticks_by_instrument)
    selected_risk_report = replay_production_portfolio_risk(
        selected,
        spot_history=spot_history,
        config=HistoricalPortfolioRiskConfig(
            starting_balance=SELECTED_STARTING_BALANCE,
            risk_fraction=SELECTED_RISK_FRACTION,
        ),
    )
    selected_period_returns = simulate_period_returns(
        tuple(item.opportunity for item in selected),
        period_start=start,
        period_end=end,
        risk_fraction_per_trade=SELECTED_RISK_FRACTION,
    )

    return {
        "schema_version": "structured-zone-development-diagnostics-v2",
        "research_role": (
            "POST-OUTCOME exploratory diagnostics on the already-opened Jan-Mar 2026 development tape; "
            "not a predeclared test and not validation evidence"
        ),
        "period": {"start": start, "end_exclusive": end, "warmup_start": history_start},
        "per_instrument": per_instrument,
        "baseline_executions": len(baseline),
        "desired_kind_zone_available": len(available),
        "desired_kind_zone_unavailable": len(unavailable),
        "availability_fraction": Decimal(len(available)) / Decimal(len(baseline)) if baseline else Decimal("0"),
        "pattern_counts": dict(sorted(patterns.items())),
        "quality_distribution": _quantiles(quality_values),
        "distance_atr_distribution": _quantiles(distance_values),
        "predeclared_gate_diagnostics": {
            "quality_at_least_0_50": sum(item.structured_zone.quality >= Decimal("0.50") for item in available),
            "distance_at_most_0_50_atr": sum(
                item.structured_zone.distance_atr is not None
                and item.structured_zone.distance_atr <= Decimal("0.50")
                for item in available
            ),
            "both": sum(
                item.structured_zone.quality >= Decimal("0.50")
                and item.structured_zone.distance_atr is not None
                and item.structured_zone.distance_atr <= Decimal("0.50")
                for item in available
            ),
        },
        "pattern_reports": pattern_reports,
        "exploratory_threshold_grid": grid,
        "baseline_report": _report(baseline),
        "selected_development_subpolicy": {
            "selection_status": "chosen_after_opened_tape_grid; development-only; requires fresh evidence before promotion",
            "minimum_quality": SELECTED_MINIMUM_QUALITY,
            "maximum_distance_atr": SELECTED_MAXIMUM_DISTANCE_ATR,
            "selection_rationale": (
                "quality>=0.75 was the only threshold row with positive expectancy/PF>1 across the adjacent "
                "3/5/10 ATR distance cells; 5 ATR is the middle positive cell and avoids selecting the sharp "
                "20-trade 3 ATR maximum or the semantically loose 10 ATR endpoint"
            ),
            "report": _report(selected),
            "uncertainty": _uncertainty(selected),
            "period_returns_fixed_0_15pct": selected_period_returns,
            "by_instrument": _group_reports(selected, "instrument"),
            "by_month": _group_reports(selected, "month"),
            "by_direction": _group_reports(selected, "direction"),
            "by_pattern": _group_reports(selected, "pattern"),
            "production_portfolio_risk": selected_risk_report,
        },
        "notes": [
            "The 0.50 quality / 0.50 ATR gate was frozen before the first Jan-Mar outcomes and selected 0/633.",
            "The 0.75 quality / 5 ATR subpolicy was selected only after the Jan-Mar grid was opened and is therefore development-selected, not validation evidence.",
            "No April-May sealed data or future untouched validation data is opened by this diagnostic.",
            "Real PIT macro consensus and real centralized institutional flow remain absent, so the full architecture is not yet frozen and no new untouched window may be opened.",
        ],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Diagnose structured-zone coverage on the opened Jan-Mar development tape.")
    parser.add_argument("--instruments", default="EUR_USD,GBP_USD,USD_JPY")
    parser.add_argument("--start", default="2026-01-05")
    parser.add_argument("--end", default="2026-04-01")
    parser.add_argument("--warmup-days", type=int, default=14)
    parser.add_argument("--cache-dir", default=".cache/forex-trader/public-history")
    parser.add_argument("--concurrency-per-pair", type=int, default=12)
    parser.add_argument("--maximum-holding-minutes", type=int, default=120)
    parser.add_argument("--entry-latency-ms", type=int, default=500)
    parser.add_argument("--slippage-pips", default="0.10")
    parser.add_argument("--output", default="artifacts/structured-zone-development-diagnostics-v2.json")
    args = parser.parse_args()
    report = asyncio.run(run(args))
    rendered = json.dumps(jsonable(report), indent=2, sort_keys=True)
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(rendered + "\n", encoding="utf-8")
    print(rendered)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
