from __future__ import annotations

from datetime import timedelta
from decimal import Decimal
from typing import Iterable

from forex_trader.domain.enums import DecisionDisposition
from forex_trader.domain.fundamentals import FundamentalBook
from forex_trader.domain.macro_history import PointInTimeFundamentalBook
from forex_trader.domain.models import Candle
from forex_trader.domain.strategy import SignalFusionPolicy
from forex_trader.research.candidate_stream import (
    SpreadModel,
    build_walk_forward_candidate,
    prepare_walk_forward_data,
)
from forex_trader.research.management import (
    ManagedTrade,
    ManagementPolicy,
    ManagementReport,
    evaluate_management_outcome,
    summarize_management,
)


def run_walk_forward_management_backtest(
    *,
    instrument: str,
    lower_candles: list[Candle],
    higher_candles: list[Candle],
    fundamentals: FundamentalBook | PointInTimeFundamentalBook,
    fusion_policy: SignalFusionPolicy,
    management_policy: ManagementPolicy,
    spread_pips: Decimal = Decimal("1.0"),
    spread_model: SpreadModel | None = None,
    exit_slippage_pips: Decimal = Decimal("0"),
    maximum_holding_bars: int = 24,
    lower_timeframe: timedelta = timedelta(minutes=5),
    higher_timeframe: timedelta = timedelta(hours=1),
) -> tuple[list[ManagedTrade], ManagementReport]:
    """Replay one management policy using the shared point-in-time signal constructor.

    Each policy gets its own sequential replay. The index advances by that policy's
    actual modeled holding duration, preventing later signals from being counted while
    the same-instrument position would still have been open.
    """
    if maximum_holding_bars < 1:
        raise ValueError("maximum_holding_bars must be positive")
    if spread_pips < 0 or exit_slippage_pips < 0:
        raise ValueError("management replay costs cannot be negative")
    lower, higher = prepare_walk_forward_data(lower_candles, higher_candles)
    results: list[ManagedTrade] = []
    index = 79
    while index < len(lower) - 1:
        candidate = build_walk_forward_candidate(
            instrument=instrument,
            lower=lower,
            higher=higher,
            index=index,
            fundamentals=fundamentals,
            fusion_policy=fusion_policy,
            spread_pips=spread_pips,
            spread_model=spread_model,
            lower_timeframe=lower_timeframe,
            higher_timeframe=higher_timeframe,
        )
        if candidate is None or candidate.disposition is not DecisionDisposition.TRADE:
            index += 1
            continue
        future = lower[index + 1 : index + 1 + maximum_holding_bars]
        if not future:
            break
        # A variable spread model is used for signal construction above. The management
        # evaluator currently applies a conservative constant exit spread; callers that
        # need path-specific bid/ask reconstruction must supply actual quote history rather
        # than pretending midpoint candles contain it.
        outcome = evaluate_management_outcome(
            candidate,
            future,
            management_policy,
            maximum_bars=maximum_holding_bars,
            spread_pips=spread_pips,
            exit_slippage_pips=exit_slippage_pips,
        )
        results.append(outcome)
        index += max(1, outcome.bars_held)
    if not results:
        return [], ManagementReport(
            policy_name=management_policy.name,
            trades=0,
            positive_trades=0,
            positive_fraction=Decimal("0"),
            total_r=Decimal("0"),
            average_r=Decimal("0"),
            max_drawdown_r=Decimal("0"),
            partial_frequency=Decimal("0"),
            ambiguous_fraction=Decimal("0"),
        )
    return results, summarize_management(results, policy_name=management_policy.name)


def compare_walk_forward_management_policies(
    *,
    instrument: str,
    lower_candles: list[Candle],
    higher_candles: list[Candle],
    fundamentals: FundamentalBook | PointInTimeFundamentalBook,
    fusion_policy: SignalFusionPolicy,
    policies: Iterable[ManagementPolicy],
    spread_pips: Decimal = Decimal("1.0"),
    spread_model: SpreadModel | None = None,
    exit_slippage_pips: Decimal = Decimal("0"),
    maximum_holding_bars: int = 24,
    lower_timeframe: timedelta = timedelta(minutes=5),
    higher_timeframe: timedelta = timedelta(hours=1),
) -> tuple[ManagementReport, ...]:
    policies = tuple(policies)
    if not policies:
        raise ValueError("at least one management policy is required")
    reports: list[ManagementReport] = []
    for policy in policies:
        _, report = run_walk_forward_management_backtest(
            instrument=instrument,
            lower_candles=lower_candles,
            higher_candles=higher_candles,
            fundamentals=fundamentals,
            fusion_policy=fusion_policy,
            management_policy=policy,
            spread_pips=spread_pips,
            spread_model=spread_model,
            exit_slippage_pips=exit_slippage_pips,
            maximum_holding_bars=maximum_holding_bars,
            lower_timeframe=lower_timeframe,
            higher_timeframe=higher_timeframe,
        )
        reports.append(report)
    return tuple(reports)
