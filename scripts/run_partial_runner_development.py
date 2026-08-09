from __future__ import annotations

import argparse
import asyncio
import json
from dataclasses import asdict, is_dataclass
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from enum import Enum
from pathlib import Path
from typing import Any, Sequence, cast

from forex_trader.domain.macro_history import PointInTimeFundamentalBook
from forex_trader.research.adaptive_managed_strategy import apply_shadow_regime_gate
from forex_trader.research.official_news_history import OfficialCentralBankHistoryClient, official_news_observations
from forex_trader.research.partial_runner_backtest import PartialRunnerProfile
from forex_trader.research.partial_runner_exact_generation import (
    DEFAULT_EXACT_RUNNER_PROFILES,
    generate_exact_partial_runner_opportunities,
)
from forex_trader.research.partial_runner_selection import PartialRunnerPolicyScore, select_stable_partial_runner_policies
from forex_trader.research.public_history import HistoricalNewsRecord, currencies_for_instruments, utc_range
from forex_trader.research.resilient_tick_history import ResilientDukascopyHistoryClient
from forex_trader.research.tick_backtest import TickBacktestOpportunity, filter_opportunities, simulate_daily_returns, strong_news_observation


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


def _parse_profiles(value: str | None) -> tuple[PartialRunnerProfile, ...]:
    if not value:
        return DEFAULT_EXACT_RUNNER_PROFILES
    profiles: list[PartialRunnerProfile] = []
    for raw in value.split(";"):
        first, fraction, runner = (Decimal(item.strip()) for item in raw.split(","))
        profiles.append(PartialRunnerProfile(first, fraction, runner))
    return tuple(profiles)


def _policy_opportunities(
    all_opportunities: dict[PartialRunnerProfile, tuple[TickBacktestOpportunity, ...]],
    score: PartialRunnerPolicyScore,
    *,
    start: datetime,
    end: datetime,
) -> tuple[TickBacktestOpportunity, ...]:
    values: Sequence[TickBacktestOpportunity] = all_opportunities[score.profile]
    if score.instrument is not None:
        values = tuple(item for item in values if item.instrument == score.instrument)
    if score.direction is not None:
        values = tuple(item for item in values if item.trade.direction is score.direction)
    base = filter_opportunities(values, score.strategy_filter, start=start, end=end)
    return apply_shadow_regime_gate(base, score.gate, evaluation_start=start, evaluation_end=end)


def _risk_scenarios(values: tuple[TickBacktestOpportunity, ...]) -> dict[str, object]:
    return {
        "0.15pct": _jsonable(simulate_daily_returns(values, risk_fraction_per_trade=Decimal("0.0015"))),
        "0.50pct": _jsonable(simulate_daily_returns(values, risk_fraction_per_trade=Decimal("0.005"))),
        "1.00pct": _jsonable(simulate_daily_returns(values, risk_fraction_per_trade=Decimal("0.01"))),
        "2.00pct": _jsonable(simulate_daily_returns(values, risk_fraction_per_trade=Decimal("0.02"))),
        "5.00pct_research_only": _jsonable(simulate_daily_returns(values, risk_fraction_per_trade=Decimal("0.05"))),
    }


async def run(args: argparse.Namespace) -> dict[str, object]:
    start_date = date.fromisoformat(args.start)
    end_date = date.fromisoformat(args.end)
    start, end = utc_range(start_date, end_date)
    instruments = tuple(item.strip().upper() for item in args.instruments.split(",") if item.strip())
    if not instruments:
        raise ValueError("at least one instrument is required")
    profiles = _parse_profiles(args.profiles)
    currencies = currencies_for_instruments(instruments)
    cache_dir = Path(args.cache_dir)
    cache_dir.mkdir(parents=True, exist_ok=True)

    news_client = OfficialCentralBankHistoryClient(cache_dir=cache_dir / "official-news")
    news_records: list[HistoricalNewsRecord] = []
    for currency in currencies:
        news_records.extend(await news_client.records((currency,), start, end))
    observations = official_news_observations(tuple(news_records))
    strong_news = tuple(item for item in observations if strong_news_observation(item))
    book = PointInTimeFundamentalBook(observations)

    by_profile: dict[PartialRunnerProfile, list[TickBacktestOpportunity]] = {profile: [] for profile in profiles}
    per_instrument: dict[str, dict[str, object]] = {}
    for instrument in instruments:
        history = ResilientDukascopyHistoryClient(
            cache_dir=cache_dir / "dukascopy",
            max_concurrency=args.concurrency_per_pair,
        )
        ticks = await history.ticks(instrument, start, end)
        generated = generate_exact_partial_runner_opportunities(
            instrument=instrument,
            ticks=ticks,
            fundamentals=book,
            news_observations=strong_news,
            profiles=profiles,
            maximum_holding=timedelta(minutes=args.maximum_holding_minutes),
            entry_latency=timedelta(milliseconds=args.entry_latency_ms),
            adverse_slippage_pips=Decimal(args.slippage_pips),
        )
        per_instrument[instrument] = {
            "ticks": len(ticks),
            "opportunities_per_profile": {
                profile.identity: len(values) for profile, values in generated.items()
            },
        }
        for profile, values in generated.items():
            by_profile[profile].extend(values)
        del ticks

    immutable = {
        profile: tuple(sorted(values, key=lambda item: (item.decision_time, item.instrument)))
        for profile, values in by_profile.items()
    }
    compatible = cast(dict[PartialRunnerProfile, Sequence[TickBacktestOpportunity]], immutable)
    robust, win_target = select_stable_partial_runner_policies(
        compatible,
        development_start=start,
        development_end=end,
        instruments=instruments,
        minimum_total_trades=args.minimum_development_trades,
        minimum_fold_trades=args.minimum_fold_trades,
    )

    selections: dict[str, object] = {}
    for name, score in (("robust_expectancy", robust), ("win_rate_target", win_target)):
        selected = _policy_opportunities(immutable, score, start=start, end=end)
        selections[name] = {
            "policy": _jsonable(score),
            "risk_scenarios": _risk_scenarios(selected),
            "goal_distance": {
                "economic_win_rate_minus_0_75": str(score.economic_win_rate - Decimal("0.75")),
                "lower_confidence_expectancy_r": str(score.lower_confidence_expectancy_r),
            },
        }

    return {
        "schema_version": "partial-runner-development-v1",
        "research_role": "development only; no proof claim from this artifact",
        "period": {"start": start, "end": end},
        "instruments": instruments,
        "profiles": profiles,
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
        "selection": selections,
        "next_validation_contract": {
            "candidate_window": "2026-04-15 through 2026-05-15",
            "warmup_start": "2026-04-01",
            "status": "UNTOUCHED_UNLESS_AND_UNTIL_DEVELOPMENT_POLICY_IS_FROZEN",
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Run exact partial-profit runner development research.")
    parser.add_argument("--instruments", default="EUR_USD,GBP_USD,USD_JPY")
    parser.add_argument("--start", default="2026-05-20")
    parser.add_argument("--end", default="2026-08-07")
    parser.add_argument("--profiles")
    parser.add_argument("--cache-dir", default=".cache/forex-trader/public-history")
    parser.add_argument("--output", default="artifacts/partial-runner-development.json")
    parser.add_argument("--concurrency-per-pair", type=int, default=12)
    parser.add_argument("--maximum-holding-minutes", type=int, default=120)
    parser.add_argument("--entry-latency-ms", type=int, default=500)
    parser.add_argument("--slippage-pips", default="0.10")
    parser.add_argument("--minimum-development-trades", type=int, default=30)
    parser.add_argument("--minimum-fold-trades", type=int, default=5)
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
