from __future__ import annotations

import argparse
import asyncio
import json
from dataclasses import asdict, is_dataclass
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from enum import Enum
from pathlib import Path
from typing import Any, cast

from forex_trader.domain.macro_history import PointInTimeFundamentalBook
from forex_trader.research.official_news_history import (
    OfficialCentralBankHistoryClient,
    official_news_observations,
)
from forex_trader.research.public_history import currencies_for_instruments, utc_range
from forex_trader.research.resilient_tick_history import ResilientDukascopyHistoryClient
from forex_trader.research.scalp_target import (
    FrozenScalpTargetResult,
    ScalpTargetPolicy,
    apply_scalp_target,
    evaluate_frozen_scalp_target,
    select_scalp_target_policy,
)
from forex_trader.research.tick_backtest import (
    TickBacktestOpportunity,
    generate_tick_opportunities,
    simulate_daily_returns,
    strong_news_observation,
)


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


def _risk_scenarios(
    opportunities: tuple[TickBacktestOpportunity, ...],
    policy: ScalpTargetPolicy,
    *,
    start: datetime,
    end: datetime,
) -> dict[str, object]:
    selected = apply_scalp_target(opportunities, policy, start=start, end=end)
    risks = (
        ("0.15pct", Decimal("0.0015")),
        ("0.50pct", Decimal("0.005")),
        ("1.00pct", Decimal("0.01")),
        ("2.00pct", Decimal("0.02")),
        ("5.00pct_research_only", Decimal("0.05")),
    )
    return {
        label: _jsonable(simulate_daily_returns(selected, risk_fraction_per_trade=risk))
        for label, risk in risks
    }


def _selection_block(
    frozen: FrozenScalpTargetResult,
    opportunities: tuple[TickBacktestOpportunity, ...],
) -> dict[str, object]:
    scenarios = _risk_scenarios(
        opportunities,
        frozen.policy,
        start=frozen.development_end,
        end=frozen.holdout_end,
    )
    scenario_values = cast(dict[str, dict[str, str]], scenarios)
    daily_goal_scenarios = [
        label
        for label, report in scenario_values.items()
        if Decimal(report["average_daily_return"]) >= Decimal("0.10")
    ]
    return {
        "frozen": _jsonable(frozen),
        "holdout_risk_scenarios": scenarios,
        "goal_evaluation": {
            "economic_win_rate_goal": "0.75",
            "observed_economic_win_rate": str(frozen.holdout.economic_win_rate),
            "economic_win_rate_goal_met": frozen.holdout.economic_win_rate >= Decimal("0.75"),
            "average_daily_return_goal": "0.10",
            "daily_return_goal_met_scenarios": daily_goal_scenarios,
            "target_hit_rate": str(frozen.holdout.report.win_rate),
            "positive_expectancy": frozen.holdout.report.expectancy_r > 0,
            "profit_factor_above_one": (
                frozen.holdout.report.profit_factor is not None
                and frozen.holdout.report.profit_factor > Decimal("1")
            ),
        },
    }


async def run(args: argparse.Namespace) -> dict[str, object]:
    development_start_date = date.fromisoformat(args.development_start)
    development_end_date = date.fromisoformat(args.development_end)
    holdout_end_date = date.fromisoformat(args.holdout_end)
    development_start, development_end = utc_range(development_start_date, development_end_date)
    _, holdout_end = utc_range(development_end_date, holdout_end_date)
    if holdout_end <= development_end:
        raise ValueError("holdout_end must be after development_end")

    instruments = tuple(item.strip().upper() for item in args.instruments.split(",") if item.strip())
    if not instruments:
        raise ValueError("at least one instrument is required")
    currencies = currencies_for_instruments(instruments)
    cache_dir = Path(args.cache_dir)
    cache_dir.mkdir(parents=True, exist_ok=True)

    news_client = OfficialCentralBankHistoryClient(cache_dir=cache_dir / "official-news")
    news_records = []
    for currency in currencies:
        news_records.extend(await news_client.records((currency,), development_start, holdout_end))
    observations = official_news_observations(tuple(news_records))
    strong_news = tuple(item for item in observations if strong_news_observation(item))
    fundamental_book = PointInTimeFundamentalBook(observations)

    opportunities: list[TickBacktestOpportunity] = []
    per_instrument: dict[str, dict[str, int]] = {}
    for instrument in instruments:
        history = ResilientDukascopyHistoryClient(
            cache_dir=cache_dir / "dukascopy",
            max_concurrency=args.concurrency_per_pair,
        )
        ticks = await history.ticks(instrument, development_start, holdout_end)
        generated = generate_tick_opportunities(
            instrument=instrument,
            ticks=ticks,
            fundamentals=fundamental_book,
            news_observations=strong_news,
            maximum_holding=timedelta(minutes=args.maximum_holding_minutes),
            entry_latency=timedelta(milliseconds=args.entry_latency_ms),
            adverse_slippage_pips=Decimal(args.slippage_pips),
        )
        opportunities.extend(generated)
        per_instrument[instrument] = {"ticks": len(ticks), "opportunities": len(generated)}
        del ticks

    opportunities.sort(key=lambda item: (item.decision_time, item.instrument))
    opportunity_tuple = tuple(opportunities)
    robust, win_target = select_scalp_target_policy(
        opportunity_tuple,
        development_start=development_start,
        development_end=development_end,
        instruments=instruments,
        minimum_trades=args.minimum_development_trades,
    )
    robust_frozen = evaluate_frozen_scalp_target(
        opportunity_tuple,
        selection=robust,
        development_start=development_start,
        development_end=development_end,
        holdout_end=holdout_end,
        objective="lower_confidence_expectancy",
    )
    win_frozen = evaluate_frozen_scalp_target(
        opportunity_tuple,
        selection=win_target,
        development_start=development_start,
        development_end=development_end,
        holdout_end=holdout_end,
        objective="economic_win_rate_target_with_positive_expectancy",
    )

    return {
        "schema_version": "official-scalp-target-backtest-v1",
        "period": {
            "development_start": development_start,
            "development_end": development_end,
            "sealed_holdout_start": development_end,
            "sealed_holdout_end": holdout_end,
        },
        "holdout_contract": {
            "selection_uses_holdout": False,
            "prior_v0_7_28_first_look_ended": development_end,
            "new_holdout_was_not_in_prior_campaign": True,
            "availability_timestamp_mode": (
                "conservative original structural-exit timestamp; scalp targets can only release capital earlier"
            ),
        },
        "data_sources": {
            "price": "Dukascopy public BI5 exact best bid/ask ticks with first-party host fallback",
            "news": "Federal Reserve, ECB, Bank of England, and Bank of Japan first-party publications",
            "limitations": [
                "Central-bank publications do not substitute for licensed point-in-time CPI/NFP consensus history.",
                "Target retiming uses exact chronological MFE evidence from the tick evaluator; original later exit timestamps are retained conservatively for overlap/day allocation.",
                "The 5% risk scenario is research-only and is not production-authorized risk.",
            ],
        },
        "execution_assumptions": {
            "observed_historical_spread": True,
            "entry_latency_ms": args.entry_latency_ms,
            "adverse_slippage_pips_each_side": args.slippage_pips,
            "structural_stop_unchanged": True,
            "maximum_holding_minutes": args.maximum_holding_minutes,
        },
        "instruments": instruments,
        "currencies": currencies,
        "news_records": len(news_records),
        "strong_news_observations": len(strong_news),
        "per_instrument": per_instrument,
        "total_opportunities": len(opportunity_tuple),
        "selection": {
            "robust_expectancy": _selection_block(robust_frozen, opportunity_tuple),
            "win_rate_target": _selection_block(win_frozen, opportunity_tuple),
        },
        "goal_definition": {
            "win_rate": "economic P/L win rate (r_multiple > 0), not merely structural-target hit rate",
            "daily_return": "compounded realized return by New York trading day",
            "targets": {"win_rate": "0.75", "average_daily_return": "0.10"},
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Optimize scalp targets on development data and test a later sealed holdout.")
    parser.add_argument("--instruments", default="EUR_USD,GBP_USD,USD_JPY")
    parser.add_argument("--development-start", default="2026-06-27")
    parser.add_argument("--development-end", default="2026-08-01")
    parser.add_argument("--holdout-end", default="2026-08-07")
    parser.add_argument("--cache-dir", default=".cache/forex-trader/public-history")
    parser.add_argument("--output", default="artifacts/official-scalp-target-backtest.json")
    parser.add_argument("--concurrency-per-pair", type=int, default=12)
    parser.add_argument("--maximum-holding-minutes", type=int, default=120)
    parser.add_argument("--entry-latency-ms", type=int, default=500)
    parser.add_argument("--slippage-pips", default="0.10")
    parser.add_argument("--minimum-development-trades", type=int, default=30)
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
