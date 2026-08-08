from __future__ import annotations

import argparse
import asyncio
import json
from dataclasses import asdict, is_dataclass
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from enum import Enum
from pathlib import Path
from typing import Any

from forex_trader.domain.macro_history import PointInTimeFundamentalBook
from forex_trader.research.public_history import (
    DukascopyHistoryClient,
    GdeltDocHistoryClient,
    currencies_for_instruments,
    gdelt_news_observations,
    utc_range,
)
from forex_trader.research.tick_backtest import (
    NewsFilter,
    SessionFilter,
    StrategyFilter,
    evaluate_frozen_filter,
    filter_opportunities,
    generate_tick_opportunities,
    select_filters_on_calibration,
    simulate_daily_returns,
    strong_news_observation,
)


def _jsonable(value: Any) -> Any:
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, datetime):
        return value.astimezone(UTC).isoformat()
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, Enum):
        return value.value
    if is_dataclass(value):
        return {key: _jsonable(item) for key, item in asdict(value).items()}
    if isinstance(value, dict):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(item) for item in value]
    return value


def _parse_date(value: str) -> date:
    return date.fromisoformat(value)


def _default_dates(*, days: int, lag_days: int) -> tuple[date, date]:
    end = (datetime.now(UTC) - timedelta(days=lag_days)).date()
    return end - timedelta(days=days), end


async def _download_news(
    *,
    currencies: tuple[str, ...],
    start: datetime,
    end: datetime,
    cache_dir: Path,
) -> tuple[Any, ...]:
    # Query one currency at a time to keep GDELT request concurrency polite and stable.
    client = GdeltDocHistoryClient(cache_dir=cache_dir / "gdelt")
    records: list[Any] = []
    for currency in currencies:
        records.extend(await client.records((currency,), start, end))
    return tuple(records)


async def _download_ticks(
    *,
    instruments: tuple[str, ...],
    start: datetime,
    end: datetime,
    cache_dir: Path,
    concurrency_per_pair: int,
) -> dict[str, tuple[Any, ...]]:
    async def load(instrument: str) -> tuple[str, tuple[Any, ...]]:
        client = DukascopyHistoryClient(
            cache_dir=cache_dir / "dukascopy",
            max_concurrency=concurrency_per_pair,
        )
        return instrument, await client.ticks(instrument, start, end)

    results = await asyncio.gather(*(load(instrument) for instrument in instruments))
    return dict(results)


def _baseline_filter(*, news: bool) -> StrategyFilter:
    return StrategyFilter(
        minimum_score=Decimal("0.68"),
        minimum_reward_risk=Decimal("1.35"),
        maximum_spread_pips=Decimal("2.0"),
        require_displacement=False,
        session_filter=SessionFilter.ALL,
        news_filter=NewsFilter.CONFLICT_VETO if news else NewsFilter.NONE,
    )


def _reports_for_risk_scenarios(opportunities: tuple[Any, ...]) -> dict[str, Any]:
    return {
        "0.15pct": _jsonable(simulate_daily_returns(opportunities, risk_fraction_per_trade=Decimal("0.0015"))),
        "0.50pct": _jsonable(simulate_daily_returns(opportunities, risk_fraction_per_trade=Decimal("0.005"))),
        "1.00pct": _jsonable(simulate_daily_returns(opportunities, risk_fraction_per_trade=Decimal("0.01"))),
    }


async def run(args: argparse.Namespace) -> dict[str, Any]:
    if args.start and args.end:
        start_date, end_date = _parse_date(args.start), _parse_date(args.end)
    elif args.start or args.end:
        raise ValueError("--start and --end must be supplied together")
    else:
        start_date, end_date = _default_dates(days=args.days, lag_days=args.lag_days)
    start, end = utc_range(start_date, end_date)
    instruments = tuple(item.strip().upper() for item in args.instruments.split(",") if item.strip())
    if not instruments:
        raise ValueError("at least one instrument is required")
    cache_dir = Path(args.cache_dir)
    cache_dir.mkdir(parents=True, exist_ok=True)

    currencies = currencies_for_instruments(instruments)
    news_records = await _download_news(
        currencies=currencies,
        start=start,
        end=end,
        cache_dir=cache_dir,
    )
    observations = gdelt_news_observations(news_records)
    strong_news = tuple(item for item in observations if strong_news_observation(item))
    fundamental_book = PointInTimeFundamentalBook(observations)

    tick_history = await _download_ticks(
        instruments=instruments,
        start=start,
        end=end,
        cache_dir=cache_dir,
        concurrency_per_pair=args.concurrency_per_pair,
    )
    opportunities: list[Any] = []
    per_instrument: dict[str, dict[str, int]] = {}
    for instrument in instruments:
        ticks = tick_history[instrument]
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
        per_instrument[instrument] = {
            "ticks": len(ticks),
            "opportunities": len(generated),
        }
    opportunities.sort(key=lambda item: (item.decision_time, item.instrument))

    duration = end - start
    calibration_end = start + duration * 2 / 3
    baseline_technical = _baseline_filter(news=False)
    baseline_news = _baseline_filter(news=True)
    baseline_technical_cal = filter_opportunities(opportunities, baseline_technical, start=start, end=calibration_end)
    baseline_technical_holdout = filter_opportunities(opportunities, baseline_technical, start=calibration_end, end=end)
    baseline_news_cal = filter_opportunities(opportunities, baseline_news, start=start, end=calibration_end)
    baseline_news_holdout = filter_opportunities(opportunities, baseline_news, start=calibration_end, end=end)

    result: dict[str, Any] = {
        "schema_version": "public-historical-backtest-v1",
        "data_sources": {
            "price": "Dukascopy public historical BI5 best bid/ask ticks",
            "news": "GDELT DOC 2.0 timestamped article headlines",
            "limitations": [
                "GDELT news is a public media overlay, not licensed point-in-time economic consensus.",
                "Dukascopy best-quote volume is not treated as centralized institutional traded volume.",
                "No OANDA credential or live-money endpoint is used by this backtest.",
            ],
        },
        "period": {"start": start, "calibration_end": calibration_end, "end": end},
        "instruments": instruments,
        "currencies": currencies,
        "news_records": len(news_records),
        "news_observations": len(observations),
        "strong_news_observations": len(strong_news),
        "per_instrument": per_instrument,
        "total_opportunities": len(opportunities),
        "execution_assumptions": {
            "entry_latency_ms": args.entry_latency_ms,
            "adverse_slippage_pips_each_side": args.slippage_pips,
            "maximum_holding_minutes": args.maximum_holding_minutes,
            "spread": "observed historical best ask minus best bid",
            "stop_target_ordering": "exact tick sequence; no same-bar ambiguity",
        },
        "baselines": {},
        "selection": {},
        "goals": {
            "win_rate": "0.75",
            "average_daily_return": "0.10",
            "note": "stretch targets only; holdout results are never modified to satisfy them",
        },
    }

    from forex_trader.research.backtest import summarize_trades

    result["baselines"] = {
        "technical_only": {
            "filter": _jsonable(baseline_technical),
            "calibration": _jsonable(summarize_trades([item.trade for item in baseline_technical_cal])),
            "holdout": _jsonable(summarize_trades([item.trade for item in baseline_technical_holdout])),
            "holdout_risk_scenarios": _reports_for_risk_scenarios(baseline_technical_holdout),
        },
        "gdelt_conflict_veto": {
            "filter": _jsonable(baseline_news),
            "calibration": _jsonable(summarize_trades([item.trade for item in baseline_news_cal])),
            "holdout": _jsonable(summarize_trades([item.trade for item in baseline_news_holdout])),
            "holdout_risk_scenarios": _reports_for_risk_scenarios(baseline_news_holdout),
        },
    }

    try:
        robust_score, win_score = select_filters_on_calibration(
            opportunities,
            calibration_start=start,
            calibration_end=calibration_end,
            minimum_trades=args.minimum_calibration_trades,
        )
    except ValueError as exc:
        result["selection"] = {"status": "insufficient_calibration_edge", "reason": str(exc)}
        return _jsonable(result)

    robust = evaluate_frozen_filter(
        opportunities,
        selection=robust_score,
        calibration_start=start,
        calibration_end=calibration_end,
        holdout_end=end,
        objective="robust_expectancy",
    )
    win_target = evaluate_frozen_filter(
        opportunities,
        selection=win_score,
        calibration_start=start,
        calibration_end=calibration_end,
        holdout_end=end,
        objective="win_rate_target_with_positive_expectancy",
    )

    for name, frozen in (("robust_expectancy", robust), ("win_rate_target", win_target)):
        holdout_selected = filter_opportunities(
            opportunities,
            frozen.strategy_filter,
            start=calibration_end,
            end=end,
        )
        result["selection"][name] = {
            "frozen": _jsonable(frozen),
            "holdout_risk_scenarios": _reports_for_risk_scenarios(holdout_selected),
            "goal_distance": {
                "win_rate_minus_goal": str(frozen.holdout_report.win_rate - Decimal("0.75")),
                "average_daily_return_minus_goal_at_current_risk": str(
                    frozen.holdout_daily_returns.average_daily_return - Decimal("0.10")
                ),
            },
        }
    return _jsonable(result)


def main() -> int:
    parser = argparse.ArgumentParser(description="Run a point-in-time public historical FX tick/news backtest.")
    parser.add_argument("--instruments", default="EUR_USD,GBP_USD,USD_JPY")
    parser.add_argument("--start")
    parser.add_argument("--end")
    parser.add_argument("--days", type=int, default=35)
    parser.add_argument("--lag-days", type=int, default=7)
    parser.add_argument("--cache-dir", default=".cache/forex-trader/public-history")
    parser.add_argument("--output", default="artifacts/public-historical-backtest.json")
    parser.add_argument("--concurrency-per-pair", type=int, default=10)
    parser.add_argument("--maximum-holding-minutes", type=int, default=120)
    parser.add_argument("--entry-latency-ms", type=int, default=500)
    parser.add_argument("--slippage-pips", default="0.10")
    parser.add_argument("--minimum-calibration-trades", type=int, default=12)
    args = parser.parse_args()
    report = asyncio.run(run(args))
    rendered = json.dumps(report, indent=2, sort_keys=True)
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(rendered + "\n", encoding="utf-8")
    print(rendered)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
