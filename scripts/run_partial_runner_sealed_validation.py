from __future__ import annotations

import argparse
import asyncio
import json
import math
from dataclasses import asdict, is_dataclass
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from enum import Enum
from pathlib import Path
from typing import Any, cast

from forex_trader.domain.macro_history import PointInTimeFundamentalBook
from forex_trader.research.adaptive_managed_strategy import economic_win_rate
from forex_trader.research.backtest import summarize_trades
from forex_trader.research.official_news_history import OfficialCentralBankHistoryClient, official_news_observations
from forex_trader.research.partial_runner_exact_generation import generate_exact_partial_runner_opportunities
from forex_trader.research.partial_runner_frozen_validation import (
    FROZEN_PARTIAL_RUNNER_DEVELOPMENT_PERIOD,
    FROZEN_PARTIAL_RUNNER_PROFILE,
    FROZEN_PARTIAL_RUNNER_SOURCE_SHA,
    apply_frozen_partial_runner_policy,
    frozen_policy_identity,
)
from forex_trader.research.public_history import HistoricalNewsRecord, currencies_for_instruments, utc_range
from forex_trader.research.resilient_tick_history import ResilientDukascopyHistoryClient
from forex_trader.research.tick_backtest import TickBacktestOpportunity, simulate_daily_returns, strong_news_observation


def _jsonable(value: object) -> object:
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, datetime):
        return value.astimezone(UTC).isoformat()
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, Enum):
        return value.value
    if is_dataclass(value) and not isinstance(value, type):
        raw = asdict(cast(Any, value))
        return {str(key): _jsonable(item) for key, item in raw.items()}
    if isinstance(value, dict):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(item) for item in value]
    return value


def _lower_confidence_expectancy(values: tuple[TickBacktestOpportunity, ...]) -> Decimal:
    if len(values) < 2:
        return Decimal("-999")
    mean = sum((item.trade.r_multiple for item in values), Decimal("0")) / Decimal(len(values))
    variance = sum(
        ((item.trade.r_multiple - mean) ** 2 for item in values), Decimal("0")
    ) / Decimal(len(values) - 1)
    standard_error = Decimal(str(math.sqrt(max(0.0, float(variance) / len(values)))))
    return mean - Decimal("1.645") * standard_error


def _risk_scenarios(values: tuple[TickBacktestOpportunity, ...]) -> dict[str, object]:
    return {
        "0.15pct": _jsonable(simulate_daily_returns(values, risk_fraction_per_trade=Decimal("0.0015"))),
        "0.50pct": _jsonable(simulate_daily_returns(values, risk_fraction_per_trade=Decimal("0.005"))),
        "1.00pct": _jsonable(simulate_daily_returns(values, risk_fraction_per_trade=Decimal("0.01"))),
        "2.00pct": _jsonable(simulate_daily_returns(values, risk_fraction_per_trade=Decimal("0.02"))),
        "5.00pct_research_only": _jsonable(simulate_daily_returns(values, risk_fraction_per_trade=Decimal("0.05"))),
    }


async def run(args: argparse.Namespace) -> dict[str, object]:
    warmup_date = date.fromisoformat(args.warmup_start)
    validation_date = date.fromisoformat(args.validation_start)
    end_date = date.fromisoformat(args.validation_end)
    warmup_start, validation_end = utc_range(warmup_date, end_date)
    validation_start, _ = utc_range(validation_date, end_date)
    instruments = tuple(item.strip().upper() for item in args.instruments.split(",") if item.strip())
    if not instruments:
        raise ValueError("at least one instrument is required")
    if not warmup_start < validation_start < validation_end:
        raise ValueError("expected warmup_start < validation_start < validation_end")

    cache_dir = Path(args.cache_dir)
    cache_dir.mkdir(parents=True, exist_ok=True)
    currencies = currencies_for_instruments(instruments)

    news_client = OfficialCentralBankHistoryClient(cache_dir=cache_dir / "official-news")
    news_records: list[HistoricalNewsRecord] = []
    for currency in currencies:
        news_records.extend(await news_client.records((currency,), warmup_start, validation_end))
    observations = official_news_observations(tuple(news_records))
    strong_news = tuple(item for item in observations if strong_news_observation(item))
    book = PointInTimeFundamentalBook(observations)

    opportunities: list[TickBacktestOpportunity] = []
    per_instrument: dict[str, object] = {}
    for instrument in instruments:
        history = ResilientDukascopyHistoryClient(
            cache_dir=cache_dir / "dukascopy",
            max_concurrency=args.concurrency_per_pair,
        )
        ticks = await history.ticks(instrument, warmup_start, validation_end)
        generated = generate_exact_partial_runner_opportunities(
            instrument=instrument,
            ticks=ticks,
            fundamentals=book,
            news_observations=strong_news,
            profiles=(FROZEN_PARTIAL_RUNNER_PROFILE,),
            maximum_holding=timedelta(minutes=args.maximum_holding_minutes),
            entry_latency=timedelta(milliseconds=args.entry_latency_ms),
            adverse_slippage_pips=Decimal(args.slippage_pips),
        )[FROZEN_PARTIAL_RUNNER_PROFILE]
        opportunities.extend(generated)
        per_instrument[instrument] = {
            "ticks": len(ticks),
            "generated_opportunities": len(generated),
        }
        del ticks

    immutable = tuple(sorted(opportunities, key=lambda item: (item.decision_time, item.instrument)))
    selected = apply_frozen_partial_runner_policy(
        immutable,
        warmup_start=warmup_start,
        validation_start=validation_start,
        validation_end=validation_end,
    )
    report = summarize_trades([item.trade for item in selected])
    win_rate = economic_win_rate(selected)
    lcb = _lower_confidence_expectancy(selected)
    proof_floor = args.minimum_proof_trades

    return {
        "schema_version": "partial-runner-sealed-validation-v1",
        "research_role": "untouched sealed validation; frozen policy; no validation-period selection",
        "frozen_policy": {
            "identity": frozen_policy_identity(),
            "source_development_period": FROZEN_PARTIAL_RUNNER_DEVELOPMENT_PERIOD,
            "source_development_sha": FROZEN_PARTIAL_RUNNER_SOURCE_SHA,
        },
        "period": {
            "shadow_warmup_start": warmup_start,
            "untouched_validation_start": validation_start,
            "untouched_validation_end_exclusive": validation_end,
        },
        "instruments": instruments,
        "news_records": len(news_records),
        "strong_news_observations": len(strong_news),
        "per_instrument": per_instrument,
        "execution_assumptions": {
            "exact_bid_ask_tick_order": True,
            "entry_latency_ms": args.entry_latency_ms,
            "adverse_slippage_pips_each_side": args.slippage_pips,
            "structural_stop_before_first_target": True,
            "runner_stop_after_first_target": "entry_fill_break_even",
            "partial_and_final_exit_times": "actual triggering tick timestamps",
        },
        "untouched_validation": {
            "report": _jsonable(report),
            "economic_wins": sum(item.trade.r_multiple > 0 for item in selected),
            "economic_win_rate": str(win_rate),
            "lower_confidence_expectancy_r": str(lcb),
            "risk_scenarios": _risk_scenarios(selected),
        },
        "goal_evaluation": {
            "minimum_proof_trades": proof_floor,
            "sample_floor_met": report.trades >= proof_floor,
            "win_rate_at_least_75pct": win_rate >= Decimal("0.75"),
            "positive_expectancy": report.expectancy_r > 0,
            "profit_factor_above_one": report.profit_factor > 1,
            "positive_lower_confidence_expectancy": lcb > 0,
            "historical_75pct_proof": (
                report.trades >= proof_floor
                and win_rate >= Decimal("0.75")
                and report.expectancy_r > 0
                and report.profit_factor > 1
            ),
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Run the frozen partial-runner policy on a sealed historical window.")
    parser.add_argument("--instruments", default="EUR_USD,GBP_USD,USD_JPY")
    parser.add_argument("--warmup-start", default="2026-04-01")
    parser.add_argument("--validation-start", default="2026-04-15")
    parser.add_argument("--validation-end", default="2026-05-16")
    parser.add_argument("--cache-dir", default=".cache/forex-trader/public-history")
    parser.add_argument("--output", default="artifacts/partial-runner-sealed-validation.json")
    parser.add_argument("--concurrency-per-pair", type=int, default=12)
    parser.add_argument("--maximum-holding-minutes", type=int, default=120)
    parser.add_argument("--entry-latency-ms", type=int, default=500)
    parser.add_argument("--slippage-pips", default="0.10")
    parser.add_argument("--minimum-proof-trades", type=int, default=20)
    args = parser.parse_args()
    report = asyncio.run(run(args))
    rendered = json.dumps(_jsonable(report), indent=2, sort_keys=True)
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(rendered + "\n", encoding="utf-8")
    print(rendered)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
