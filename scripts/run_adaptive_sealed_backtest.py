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
from forex_trader.research.adaptive_managed_strategy import (
    AdaptivePolicyReport,
    evaluate_frozen_adaptive_policy,
    select_stable_adaptive_policies,
)
from forex_trader.research.managed_tick_backtest import generate_profit_target_opportunities
from forex_trader.research.official_news_history import (
    OfficialCentralBankHistoryClient,
    official_news_observations,
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


def _parse_targets(value: str) -> tuple[Decimal, ...]:
    targets = tuple(Decimal(item.strip()) for item in value.split(",") if item.strip())
    if not targets:
        raise ValueError("at least one target is required")
    return targets


def _risk_scenarios(opportunities: tuple[TickBacktestOpportunity, ...]) -> dict[str, object]:
    risks = (
        ("0.15pct", Decimal("0.0015")),
        ("0.50pct", Decimal("0.005")),
        ("1.00pct", Decimal("0.01")),
        ("2.00pct", Decimal("0.02")),
        ("5.00pct_research_only", Decimal("0.05")),
    )
    return {
        label: _jsonable(simulate_daily_returns(opportunities, risk_fraction_per_trade=risk))
        for label, risk in risks
    }


def _selection_result(
    policy_report: AdaptivePolicyReport,
    opportunities_by_target: dict[Decimal, tuple[TickBacktestOpportunity, ...]],
    *,
    history_start: datetime,
    validation_start: datetime,
    validation_end: datetime,
    minimum_proof_trades: int,
) -> dict[str, object]:
    compatible = cast(dict[Decimal, Sequence[TickBacktestOpportunity]], opportunities_by_target)
    selected, report, economic_win_rate = evaluate_frozen_adaptive_policy(
        compatible,
        policy_report=policy_report,
        history_start=history_start,
        evaluation_start=validation_start,
        evaluation_end=validation_end,
    )
    scenarios = _risk_scenarios(selected)
    scenario_values = cast(dict[str, dict[str, str]], scenarios)
    daily_goal_all = [
        label
        for label, metrics in scenario_values.items()
        if Decimal(metrics["average_daily_return"]) >= Decimal("0.10")
    ]
    daily_goal_at_or_below_2pct = [
        label
        for label in ("0.15pct", "0.50pct", "1.00pct", "2.00pct")
        if Decimal(scenario_values[label]["average_daily_return"]) >= Decimal("0.10")
    ]
    pf = report.profit_factor
    proof_sample = report.trades >= minimum_proof_trades
    edge_positive = report.expectancy_r > 0 and pf is not None and pf > Decimal("1")
    win_goal = economic_win_rate >= Decimal("0.75")
    return {
        "development_selection": _jsonable(policy_report),
        "untouched_validation": {
            "report": _jsonable(report),
            "economic_win_rate": str(economic_win_rate),
            "economic_wins": sum(item.trade.r_multiple > 0 for item in selected),
            "trades": len(selected),
            "risk_scenarios": scenarios,
        },
        "goal_evaluation": {
            "minimum_proof_trades": minimum_proof_trades,
            "sample_floor_met": proof_sample,
            "win_rate_goal": "0.75",
            "win_rate_goal_met": win_goal,
            "positive_expectancy": report.expectancy_r > 0,
            "profit_factor_above_one": pf is not None and pf > Decimal("1"),
            "average_daily_return_goal": "0.10",
            "daily_return_goal_met_scenarios": daily_goal_all,
            "daily_return_goal_met_at_or_below_2pct_risk": daily_goal_at_or_below_2pct,
            "historical_win_rate_proof": proof_sample and edge_positive and win_goal,
            "historical_joint_goal_proof_at_or_below_2pct_risk": (
                proof_sample and edge_positive and win_goal and bool(daily_goal_at_or_below_2pct)
            ),
        },
    }


async def run(args: argparse.Namespace) -> dict[str, object]:
    history_start_date = date.fromisoformat(args.history_start)
    validation_start_date = date.fromisoformat(args.validation_start)
    validation_end_date = date.fromisoformat(args.validation_end)
    development_start_date = date.fromisoformat(args.development_start)
    development_end_date = date.fromisoformat(args.development_end)
    history_start, development_end = utc_range(history_start_date, development_end_date)
    _, validation_start = utc_range(history_start_date, validation_start_date)
    _, validation_end = utc_range(history_start_date, validation_end_date)
    _, development_start = utc_range(history_start_date, development_start_date)
    if not history_start < validation_start < validation_end <= development_start < development_end:
        raise ValueError("expected history < validation < development chronological boundaries")

    instruments = tuple(item.strip().upper() for item in args.instruments.split(",") if item.strip())
    if not instruments:
        raise ValueError("at least one instrument is required")
    targets = _parse_targets(args.profit_targets)
    currencies = currencies_for_instruments(instruments)
    cache_dir = Path(args.cache_dir)
    cache_dir.mkdir(parents=True, exist_ok=True)

    news_client = OfficialCentralBankHistoryClient(cache_dir=cache_dir / "official-news")
    news_records: list[HistoricalNewsRecord] = []
    for currency in currencies:
        news_records.extend(await news_client.records((currency,), history_start, development_end))
    observations = official_news_observations(tuple(news_records))
    strong_news = tuple(item for item in observations if strong_news_observation(item))
    fundamental_book = PointInTimeFundamentalBook(observations)

    opportunities_by_target: dict[Decimal, list[TickBacktestOpportunity]] = {target: [] for target in targets}
    per_instrument: dict[str, dict[str, object]] = {}
    for instrument in instruments:
        history = ResilientDukascopyHistoryClient(
            cache_dir=cache_dir / "dukascopy",
            max_concurrency=args.concurrency_per_pair,
        )
        ticks = await history.ticks(instrument, history_start, development_end)
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
            "opportunities_per_target": {str(target): len(values) for target, values in generated.items()},
        }
        for target, values in generated.items():
            opportunities_by_target[target].extend(values)
        del ticks

    immutable_by_target = {
        target: tuple(sorted(values, key=lambda item: (item.decision_time, item.instrument)))
        for target, values in opportunities_by_target.items()
    }
    compatible = cast(dict[Decimal, Sequence[TickBacktestOpportunity]], immutable_by_target)
    robust, win_target = select_stable_adaptive_policies(
        compatible,
        development_start=development_start,
        development_end=development_end,
        instruments=instruments,
        minimum_total_trades=args.minimum_development_trades,
        minimum_fold_trades=args.minimum_fold_trades,
    )

    result: dict[str, object] = {
        "schema_version": "adaptive-managed-sealed-backtest-v1",
        "period": {
            "shadow_history_start": history_start,
            "untouched_validation_start": validation_start,
            "untouched_validation_end": validation_end,
            "development_start": development_start,
            "development_end": development_end,
        },
        "validation_contract": {
            "selection_uses_validation": False,
            "validation_window_used_by_prior_v0_7_28_campaigns": False,
            "development_includes_previously_inspected_june28_aug7_history": True,
            "regime_gate_uses_only_shadow_outcomes_completed_before_each_decision": True,
            "minimum_validation_trades_for_proof": args.minimum_proof_trades,
        },
        "instruments": instruments,
        "currencies": currencies,
        "profit_target_grid_r": targets,
        "news_records": len(news_records),
        "strong_news_observations": len(strong_news),
        "per_instrument": per_instrument,
        "execution_assumptions": {
            "observed_historical_spread": True,
            "entry_latency_ms": args.entry_latency_ms,
            "adverse_slippage_pips_each_side": args.slippage_pips,
            "structural_stop_unchanged": True,
            "exact_target_exit_timestamp": True,
            "maximum_holding_minutes": args.maximum_holding_minutes,
        },
        "data_sources": {
            "price": "Dukascopy public BI5 exact best bid/ask ticks with first-party host fallback",
            "news": "Federal Reserve, ECB, Bank of England, and Bank of Japan first-party publications",
        },
        "selection": {
            "robust_expectancy": _selection_result(
                robust,
                immutable_by_target,
                history_start=history_start,
                validation_start=validation_start,
                validation_end=validation_end,
                minimum_proof_trades=args.minimum_proof_trades,
            ),
            "win_rate_target": _selection_result(
                win_target,
                immutable_by_target,
                history_start=history_start,
                validation_start=validation_start,
                validation_end=validation_end,
                minimum_proof_trades=args.minimum_proof_trades,
            ),
        },
        "goals": {
            "economic_win_rate": "0.75",
            "average_daily_return": "0.10",
            "rule": "validation results are preserved whether or not goals are met",
        },
    }
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description="Select a causal regime-gated scalp policy and test an untouched period.")
    parser.add_argument("--instruments", default="EUR_USD,GBP_USD,USD_JPY")
    parser.add_argument("--history-start", default="2026-05-20")
    parser.add_argument("--validation-start", default="2026-06-01")
    parser.add_argument("--validation-end", default="2026-06-28")
    parser.add_argument("--development-start", default="2026-06-28")
    parser.add_argument("--development-end", default="2026-08-07")
    parser.add_argument("--profit-targets", default="0.25,0.33,0.35,0.40,0.50,0.65,0.80")
    parser.add_argument("--cache-dir", default=".cache/forex-trader/public-history")
    parser.add_argument("--output", default="artifacts/adaptive-managed-sealed-backtest.json")
    parser.add_argument("--concurrency-per-pair", type=int, default=12)
    parser.add_argument("--maximum-holding-minutes", type=int, default=120)
    parser.add_argument("--entry-latency-ms", type=int, default=500)
    parser.add_argument("--slippage-pips", default="0.10")
    parser.add_argument("--minimum-development-trades", type=int, default=24)
    parser.add_argument("--minimum-fold-trades", type=int, default=4)
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
