from __future__ import annotations

import argparse
import asyncio
import json
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

from forex_trader.domain.macro_history import PointInTimeFundamentalBook
from forex_trader.research.backtest import summarize_trades
from forex_trader.research.managed_tick_backtest import (
    DEFAULT_PROFIT_TARGETS_R,
    evaluate_managed_selection,
    generate_profit_target_opportunities,
    select_managed_profiles_on_calibration,
)
from forex_trader.research.official_news_history import (
    OfficialCentralBankHistoryClient,
    official_news_observations,
)
from forex_trader.research.public_history import currencies_for_instruments, utc_range
from forex_trader.research.resilient_tick_history import ResilientDukascopyHistoryClient
from forex_trader.research.tick_backtest import (
    filter_opportunities,
    simulate_daily_returns,
    strong_news_observation,
)
from scripts.run_public_historical_backtest import _jsonable


def _parse_targets(value: str) -> tuple[Decimal, ...]:
    targets = tuple(Decimal(item.strip()) for item in value.split(",") if item.strip())
    if not targets:
        raise ValueError("at least one profit target is required")
    return targets


def _dates(args: argparse.Namespace) -> tuple[datetime, datetime]:
    if args.start and args.end:
        start_date = datetime.fromisoformat(args.start).date()
        end_date = datetime.fromisoformat(args.end).date()
    elif args.start or args.end:
        raise ValueError("--start and --end must be supplied together")
    else:
        end_date = (datetime.now(UTC) - timedelta(days=args.lag_days)).date()
        start_date = end_date - timedelta(days=args.days)
    return utc_range(start_date, end_date)


def _risk_scenarios(opportunities: tuple[object, ...]) -> dict[str, object]:
    typed = tuple(opportunities)  # narrow only at the call boundary
    return {
        "0.15pct": _jsonable(simulate_daily_returns(typed, risk_fraction_per_trade=Decimal("0.0015"))),  # type: ignore[arg-type]
        "0.50pct": _jsonable(simulate_daily_returns(typed, risk_fraction_per_trade=Decimal("0.005"))),  # type: ignore[arg-type]
        "1.00pct": _jsonable(simulate_daily_returns(typed, risk_fraction_per_trade=Decimal("0.01"))),  # type: ignore[arg-type]
        "2.00pct": _jsonable(simulate_daily_returns(typed, risk_fraction_per_trade=Decimal("0.02"))),  # type: ignore[arg-type]
        "5.00pct": _jsonable(simulate_daily_returns(typed, risk_fraction_per_trade=Decimal("0.05"))),  # type: ignore[arg-type]
    }


async def run(args: argparse.Namespace) -> dict[str, object]:
    start, end = _dates(args)
    instruments = tuple(item.strip().upper() for item in args.instruments.split(",") if item.strip())
    if not instruments:
        raise ValueError("at least one instrument is required")
    targets = _parse_targets(args.profit_targets)
    cache_dir = Path(args.cache_dir)
    cache_dir.mkdir(parents=True, exist_ok=True)

    currencies = currencies_for_instruments(instruments)
    news_client = OfficialCentralBankHistoryClient(cache_dir=cache_dir / "official-news")
    news_records = await news_client.records(currencies, start, end)
    observations = official_news_observations(news_records)
    strong_news = tuple(item for item in observations if strong_news_observation(item))
    fundamental_book = PointInTimeFundamentalBook(observations)

    by_target: dict[Decimal, list[object]] = {target: [] for target in targets}
    per_instrument: dict[str, dict[str, object]] = {}
    for instrument in instruments:
        tick_client = ResilientDukascopyHistoryClient(
            cache_dir=cache_dir / "dukascopy",
            max_concurrency=args.concurrency_per_pair,
        )
        ticks = await tick_client.ticks(instrument, start, end)
        generated = generate_profit_target_opportunities(
            instrument=instrument,
            ticks=ticks,
            fundamentals=fundamental_book,
            news_observations=strong_news,
            take_profit_targets_r=targets,
            maximum_holding=timedelta(minutes=args.maximum_holding_minutes),
            entry_latency=timedelta(milliseconds=args.entry_latency_ms),
            adverse_slippage_pips=Decimal(args.slippage_pips),
        )
        per_instrument[instrument] = {
            "ticks": len(ticks),
            "opportunities_per_target": {str(target): len(items) for target, items in generated.items()},
        }
        for target, items in generated.items():
            by_target[target].extend(items)
        del ticks

    typed_by_target = {
        target: tuple(sorted(items, key=lambda item: (item.decision_time, item.instrument)))  # type: ignore[attr-defined]
        for target, items in by_target.items()
    }
    duration = end - start
    calibration_end = start + duration * 2 / 3

    leaderboard: list[dict[str, object]] = []
    from forex_trader.research.tick_backtest import select_filters_on_calibration

    for target, opportunities in sorted(typed_by_target.items()):
        try:
            robust, win = select_filters_on_calibration(
                opportunities,  # type: ignore[arg-type]
                calibration_start=start,
                calibration_end=calibration_end,
                minimum_trades=args.minimum_calibration_trades,
            )
        except ValueError as exc:
            leaderboard.append({"take_profit_r": str(target), "status": "no_positive_edge", "reason": str(exc)})
            continue
        leaderboard.append(
            {
                "take_profit_r": str(target),
                "robust_filter": _jsonable(robust.strategy_filter),
                "robust_calibration": _jsonable(robust.report),
                "robust_lower_confidence_expectancy_r": str(robust.lower_confidence_expectancy_r),
                "win_filter": _jsonable(win.strategy_filter),
                "win_calibration": _jsonable(win.report),
                "win_lower_confidence_expectancy_r": str(win.lower_confidence_expectancy_r),
            }
        )

    result: dict[str, object] = {
        "schema_version": "managed-public-historical-backtest-v1",
        "research_role": "development_selection; final proof requires disjoint frozen validation",
        "period": {"start": start, "calibration_end": calibration_end, "end": end},
        "instruments": instruments,
        "currencies": currencies,
        "profit_target_grid_r": targets,
        "news_records": len(news_records),
        "news_observations": len(observations),
        "strong_news_observations": len(strong_news),
        "per_instrument": per_instrument,
        "execution_assumptions": {
            "entry_latency_ms": args.entry_latency_ms,
            "adverse_slippage_pips_each_side": args.slippage_pips,
            "maximum_holding_minutes": args.maximum_holding_minutes,
            "spread": "observed Dukascopy best ask minus best bid",
            "stop": "original structural stop from the production technical setup",
            "take_profit": "fixed R target selected on calibration only",
            "stop_target_ordering": "exact executable tick sequence",
        },
        "target_calibration_leaderboard": leaderboard,
        "selection": {},
        "goals": {
            "win_rate": "0.75",
            "average_daily_return": "0.10",
            "rule": "targets are goals, never assertions; negative or insufficient OOS evidence is preserved",
        },
        "data_sources": {
            "price": "Dukascopy public historical BI5 best bid/ask ticks with first-party host fallback",
            "news": "Federal Reserve, ECB, Bank of England, and Bank of Japan first-party feeds",
        },
    }

    try:
        robust_selection, win_selection = select_managed_profiles_on_calibration(
            typed_by_target,  # type: ignore[arg-type]
            calibration_start=start,
            calibration_end=calibration_end,
            minimum_trades=args.minimum_calibration_trades,
        )
    except ValueError as exc:
        result["selection"] = {"status": "insufficient_calibration_edge", "reason": str(exc)}
        return result

    selections: dict[str, object] = {}
    for name, managed_selection in (
        ("robust_expectancy", robust_selection),
        ("win_rate_target", win_selection),
    ):
        managed = evaluate_managed_selection(
            typed_by_target,  # type: ignore[arg-type]
            managed_selection=managed_selection,
            calibration_start=start,
            calibration_end=calibration_end,
            holdout_end=end,
            objective=name,
        )
        frozen = managed.frozen
        opportunities = typed_by_target[managed.take_profit_r]
        selected_holdout = filter_opportunities(
            opportunities,  # type: ignore[arg-type]
            frozen.strategy_filter,  # type: ignore[attr-defined]
            start=calibration_end,
            end=end,
        )
        calibration_selected = filter_opportunities(
            opportunities,  # type: ignore[arg-type]
            frozen.strategy_filter,  # type: ignore[attr-defined]
            start=start,
            end=calibration_end,
        )
        selections[name] = {
            "take_profit_r": str(managed.take_profit_r),
            "frozen": _jsonable(frozen),
            "calibration_selected_summary": _jsonable(
                summarize_trades([item.trade for item in calibration_selected])
            ),
            "holdout_risk_scenarios": _risk_scenarios(tuple(selected_holdout)),
        }
    result["selection"] = selections
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description="Run exact multi-target FX management research on public history.")
    parser.add_argument("--instruments", default="EUR_USD,GBP_USD,USD_JPY")
    parser.add_argument("--start")
    parser.add_argument("--end")
    parser.add_argument("--days", type=int, default=35)
    parser.add_argument("--lag-days", type=int, default=7)
    parser.add_argument("--cache-dir", default=".cache/forex-trader/public-history")
    parser.add_argument("--output", default="artifacts/managed-public-historical-backtest.json")
    parser.add_argument("--profit-targets", default=",".join(str(value) for value in DEFAULT_PROFIT_TARGETS_R))
    parser.add_argument("--concurrency-per-pair", type=int, default=12)
    parser.add_argument("--maximum-holding-minutes", type=int, default=120)
    parser.add_argument("--entry-latency-ms", type=int, default=500)
    parser.add_argument("--slippage-pips", default="0.10")
    parser.add_argument("--minimum-calibration-trades", type=int, default=10)
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
