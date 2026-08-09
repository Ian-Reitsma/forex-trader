from __future__ import annotations

import argparse
import asyncio
import bisect
import json
from collections import Counter
from datetime import date, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Sequence

from forex_trader.domain.enums import DecisionDisposition
from forex_trader.domain.macro_history import PointInTimeFundamentalBook
from forex_trader.domain.models import Quote, jsonable
from forex_trader.domain.strategy import SignalFusionPolicy
from forex_trader.domain.technicals import assess_technicals
from forex_trader.research.public_history import HistoricalTick, resample_midpoint_candles, utc_range
from forex_trader.research.resilient_tick_history import ResilientDukascopyHistoryClient
from scripts.run_staged_historical_development import (
    STRUCTURED_ZONE_MAXIMUM_DISTANCE_ATR,
    STRUCTURED_ZONE_MINIMUM_QUALITY,
    StructuredZoneEvidence,
    _structured_zone_evidence,
)


def _quantiles(values: Sequence[Decimal]) -> dict[str, Decimal] | None:
    if not values:
        return None
    ordered = sorted(values)

    def pick(fraction: Decimal) -> Decimal:
        if len(ordered) == 1:
            return ordered[0]
        index = int((Decimal(len(ordered) - 1) * fraction).to_integral_value(rounding="ROUND_HALF_UP"))
        return ordered[index]

    return {
        "min": ordered[0],
        "p10": pick(Decimal("0.10")),
        "p25": pick(Decimal("0.25")),
        "p50": pick(Decimal("0.50")),
        "p75": pick(Decimal("0.75")),
        "p90": pick(Decimal("0.90")),
        "max": ordered[-1],
    }


def _summarize(evidence: Sequence[StructuredZoneEvidence]) -> dict[str, object]:
    available = tuple(item for item in evidence if item.available)
    quality_pass = tuple(item for item in available if item.quality >= STRUCTURED_ZONE_MINIMUM_QUALITY)
    distance_pass = tuple(
        item
        for item in available
        if item.distance_atr is not None and item.distance_atr <= STRUCTURED_ZONE_MAXIMUM_DISTANCE_ATR
    )
    aligned = tuple(item for item in available if item.aligned)
    patterns = Counter(item.pattern or "unknown" for item in available)
    distances = tuple(item.distance_atr for item in available if item.distance_atr is not None)
    return {
        "candidate_decisions": len(evidence),
        "same_direction_unbroken_zone_available": len(available),
        "same_direction_zone_availability_fraction": Decimal(len(available)) / Decimal(len(evidence)) if evidence else Decimal("0"),
        "passes_quality_only": len(quality_pass),
        "passes_distance_only": len(distance_pass),
        "passes_frozen_quality_and_distance": len(aligned),
        "frozen_quality_threshold": STRUCTURED_ZONE_MINIMUM_QUALITY,
        "frozen_distance_atr_threshold": STRUCTURED_ZONE_MAXIMUM_DISTANCE_ATR,
        "patterns": dict(sorted(patterns.items())),
        "quality_quantiles": _quantiles(tuple(item.quality for item in available)),
        "distance_atr_quantiles": _quantiles(distances),
    }


def scan_candidate_zone_evidence(
    *,
    instrument: str,
    ticks: Sequence[HistoricalTick],
    decision_start: datetime,
    decision_end: datetime,
    lower_timeframe: timedelta = timedelta(minutes=5),
    higher_timeframe: timedelta = timedelta(hours=1),
    entry_latency: timedelta = timedelta(milliseconds=500),
    maximum_decision_quote_age: timedelta = timedelta(seconds=10),
) -> tuple[StructuredZoneEvidence, ...]:
    ordered_ticks = tuple(sorted(ticks, key=lambda item: item.time))
    if len(ordered_ticks) < 2:
        return ()
    times = tuple(item.time for item in ordered_ticks)
    lower = list(resample_midpoint_candles(ordered_ticks, timeframe=lower_timeframe))
    higher = list(resample_midpoint_candles(ordered_ticks, timeframe=higher_timeframe))
    if len(lower) < 82 or len(higher) < 60:
        return ()
    higher_ready = tuple(item.time + higher_timeframe for item in higher)
    normalized = instrument.upper()
    fundamentals = PointInTimeFundamentalBook()
    policy = SignalFusionPolicy(
        minimum_score=Decimal("0"),
        minimum_fundamental_confidence=Decimal("0"),
        maximum_spread_pips=Decimal("5"),
        maximum_quote_signal_gap_seconds=max(30, int(maximum_decision_quote_age.total_seconds()) + 5),
        minimum_reward_risk=Decimal("1.01"),
        require_fundamentals=False,
        require_liquidity_sweep=True,
        require_displacement=False,
        require_structure_shift=True,
        require_entry_confirmed=True,
        minimum_location_score=Decimal("0.15"),
    )

    result: list[StructuredZoneEvidence] = []
    for index in range(79, len(lower) - 1):
        decision_time = lower[index].time + lower_timeframe
        if decision_time < decision_start or decision_time >= decision_end:
            continue
        higher_count = bisect.bisect_right(higher_ready, decision_time)
        if higher_count < 60:
            continue
        decision_index = bisect.bisect_left(times, decision_time)
        if decision_index >= len(ordered_ticks):
            continue
        decision_tick = ordered_ticks[decision_index]
        if decision_tick.time - decision_time > maximum_decision_quote_age:
            continue
        lower_window = lower[max(0, index - 199) : index + 1]
        technical = assess_technicals(
            normalized,
            lower_window,
            higher[max(0, higher_count - 200) : higher_count],
            minimum_structural_reward_risk=Decimal("1.01"),
        )
        fundamental = fundamentals.assess_pair(normalized, as_of=decision_time)
        candidate = policy.evaluate(
            technical,
            fundamental,
            Quote(normalized, decision_tick.bid, decision_tick.ask, decision_tick.time),
        )
        if candidate.disposition is not DecisionDisposition.TRADE:
            continue
        entry_index = bisect.bisect_left(times, decision_time + entry_latency)
        if entry_index >= len(ordered_ticks):
            continue
        entry_tick = ordered_ticks[entry_index]
        if entry_tick.time - decision_time > maximum_decision_quote_age:
            continue
        candidate = policy.revalidate_execution(
            candidate,
            Quote(normalized, entry_tick.bid, entry_tick.ask, entry_tick.time),
            maximum_spread_pips=Decimal("5"),
        )
        if candidate.disposition is not DecisionDisposition.TRADE:
            continue
        result.append(
            _structured_zone_evidence(
                technical,
                candidate,
                lower_window,
                decision_time=decision_time,
            )
        )
    return tuple(result)


async def run(args: argparse.Namespace) -> dict[str, object]:
    start, end = utc_range(date.fromisoformat(args.start), date.fromisoformat(args.end))
    history_start = start - timedelta(days=args.warmup_days)
    instruments = tuple(item.strip().upper() for item in args.instruments.split(",") if item.strip())
    if not instruments:
        raise ValueError("at least one instrument is required")
    cache_dir = Path(args.cache_dir)
    per_instrument: dict[str, object] = {}
    combined: list[StructuredZoneEvidence] = []
    for instrument in instruments:
        client = ResilientDukascopyHistoryClient(
            cache_dir=cache_dir / "dukascopy",
            max_concurrency=args.concurrency_per_pair,
        )
        ticks = await client.ticks(instrument, history_start, end)
        evidence = scan_candidate_zone_evidence(
            instrument=instrument,
            ticks=ticks,
            decision_start=start,
            decision_end=end,
            entry_latency=timedelta(milliseconds=args.entry_latency_ms),
        )
        combined.extend(evidence)
        per_instrument[instrument] = {
            "history_ticks_including_warmup": len(ticks),
            "structured_zone_coverage": _summarize(evidence),
        }
    return {
        "schema_version": "structured-zone-coverage-v1",
        "research_role": "outcome-blind diagnostics on the already-open Jan-Mar 2026 development tape",
        "period": {
            "development_start": start,
            "development_end_exclusive": end,
            "price_warmup_start": history_start,
            "reserved_future_validation": "NOT_OPENED_BY_THIS_RUN",
        },
        "thresholds_unchanged_from_staged_run": {
            "minimum_quality": STRUCTURED_ZONE_MINIMUM_QUALITY,
            "maximum_distance_atr": STRUCTURED_ZONE_MAXIMUM_DISTANCE_ATR,
        },
        "aggregate": _summarize(tuple(combined)),
        "per_instrument": per_instrument,
        "interpretation_contract": [
            "No future trade outcome is evaluated by this diagnostic.",
            "A zero availability count means the detector produced no same-direction unbroken structured-zone candidate at the causal decision time.",
            "Quality and distance are summarized separately so a frozen threshold can be distinguished from detector coverage.",
            "No threshold is changed by this diagnostic and no untouched validation window is read.",
        ],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Diagnose structured-zone coverage without evaluating trade outcomes.")
    parser.add_argument("--instruments", default="EUR_USD,GBP_USD,USD_JPY")
    parser.add_argument("--start", default="2026-01-05")
    parser.add_argument("--end", default="2026-04-01")
    parser.add_argument("--warmup-days", type=int, default=14)
    parser.add_argument("--cache-dir", default=".cache/forex-trader/public-history")
    parser.add_argument("--concurrency-per-pair", type=int, default=12)
    parser.add_argument("--entry-latency-ms", type=int, default=500)
    parser.add_argument("--output", default="artifacts/structured-zone-coverage-v1.json")
    args = parser.parse_args()
    if args.warmup_days < 7 or args.entry_latency_ms < 0:
        raise SystemExit("warmup must be at least 7 days and entry latency cannot be negative")
    report = asyncio.run(run(args))
    rendered = json.dumps(jsonable(report), indent=2, sort_keys=True)
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(rendered + "\n", encoding="utf-8")
    print(rendered)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
