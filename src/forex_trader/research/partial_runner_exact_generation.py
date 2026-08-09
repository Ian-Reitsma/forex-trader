from __future__ import annotations

import bisect
from datetime import timedelta
from decimal import Decimal
from typing import Sequence

from forex_trader.domain.enums import DecisionDisposition, Direction
from forex_trader.domain.macro_history import MacroObservation, PointInTimeFundamentalBook
from forex_trader.domain.models import Quote
from forex_trader.domain.sessions import classify_phase
from forex_trader.domain.strategy import SignalFusionPolicy
from forex_trader.domain.technicals import assess_technicals, pip_size
from forex_trader.research.partial_runner_backtest import PartialRunnerProfile
from forex_trader.research.partial_runner_exact import evaluate_exact_partial_runner
from forex_trader.research.public_history import HistoricalTick, resample_midpoint_candles
from forex_trader.research.tick_backtest import TickBacktestOpportunity


DEFAULT_EXACT_RUNNER_PROFILES: tuple[PartialRunnerProfile, ...] = tuple(
    PartialRunnerProfile(first, fraction, runner)
    for first in (Decimal("0.25"), Decimal("0.35"), Decimal("0.50"))
    for fraction in (Decimal("0.50"), Decimal("0.67"))
    for runner in (Decimal("1.00"), Decimal("1.50"))
)


def _latest_news_age_minutes(
    observations: Sequence[MacroObservation],
    *,
    currencies: tuple[str, str],
    as_of: object,
) -> Decimal | None:
    from datetime import datetime

    if not isinstance(as_of, datetime):
        raise TypeError("as_of must be a datetime")
    latest: datetime | None = None
    allowed = set(currencies)
    for observation in observations:
        if observation.available_at > as_of:
            break
        if observation.currency in allowed:
            latest = observation.available_at
    if latest is None:
        return None
    return Decimal(str((as_of - latest).total_seconds() / 60))


def generate_exact_partial_runner_opportunities(
    *,
    instrument: str,
    ticks: Sequence[HistoricalTick],
    fundamentals: PointInTimeFundamentalBook,
    news_observations: Sequence[MacroObservation] = (),
    profiles: Sequence[PartialRunnerProfile] = DEFAULT_EXACT_RUNNER_PROFILES,
    lower_timeframe: timedelta = timedelta(minutes=5),
    higher_timeframe: timedelta = timedelta(hours=1),
    maximum_holding: timedelta = timedelta(hours=2),
    entry_latency: timedelta = timedelta(milliseconds=500),
    adverse_slippage_pips: Decimal = Decimal("0.10"),
    maximum_decision_quote_age: timedelta = timedelta(seconds=10),
) -> dict[PartialRunnerProfile, tuple[TickBacktestOpportunity, ...]]:
    """Generate identical production-style entries under exact runner profiles."""
    profile_tuple = tuple(sorted(set(profiles)))
    if not profile_tuple:
        raise ValueError("at least one partial-runner profile is required")
    if len(ticks) < 2:
        return {profile: () for profile in profile_tuple}

    ordered_ticks = tuple(sorted(ticks, key=lambda item: item.time))
    times = [item.time for item in ordered_ticks]
    lower = list(resample_midpoint_candles(ordered_ticks, timeframe=lower_timeframe))
    higher = list(resample_midpoint_candles(ordered_ticks, timeframe=higher_timeframe))
    if len(lower) < 82 or len(higher) < 60:
        return {profile: () for profile in profile_tuple}
    higher_ready = [candle.time + higher_timeframe for candle in higher]

    normalized = instrument.upper()
    base_currency, quote_currency = normalized.split("_", maxsplit=1)
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
    opportunities: dict[PartialRunnerProfile, list[TickBacktestOpportunity]] = {
        profile: [] for profile in profile_tuple
    }

    for index in range(79, len(lower) - 1):
        signal_candle = lower[index]
        decision_time = signal_candle.time + lower_timeframe
        higher_count = bisect.bisect_right(higher_ready, decision_time)
        if higher_count < 60:
            continue
        decision_tick_index = bisect.bisect_left(times, decision_time)
        if decision_tick_index >= len(ordered_ticks):
            continue
        decision_tick = ordered_ticks[decision_tick_index]
        if decision_tick.time - decision_time > maximum_decision_quote_age:
            continue

        technical = assess_technicals(
            normalized,
            lower[max(0, index - 199) : index + 1],
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
        assert candidate.entry_price is not None
        assert candidate.stop_loss is not None
        assert candidate.take_profit is not None
        structural_rr = abs(candidate.take_profit - candidate.entry_price) / abs(
            candidate.entry_price - candidate.stop_loss
        )
        directional_news = (
            fundamental.differential
            if candidate.direction is Direction.LONG
            else -fundamental.differential
        )
        latest_news_age = _latest_news_age_minutes(
            news_observations,
            currencies=(base_currency, quote_currency),
            as_of=decision_time,
        )

        for profile in profile_tuple:
            exact = evaluate_exact_partial_runner(
                candidate,
                ordered_ticks,
                entry_index=entry_index,
                profile=profile,
                maximum_holding=maximum_holding,
                adverse_slippage_pips=adverse_slippage_pips,
            )
            opportunities[profile].append(
                TickBacktestOpportunity(
                    instrument=normalized,
                    decision_time=decision_time,
                    entry_time=exact.entry_time,
                    exit_time=exact.exit_time,
                    trade=exact.trade,
                    technical_score=technical.score,
                    reward_risk=structural_rr,
                    spread_pips=entry_tick.spread / pip_size(normalized),
                    displacement=technical.displacement,
                    session_phase=classify_phase(decision_time),
                    news_directional=directional_news,
                    news_confidence=fundamental.confidence,
                    latest_news_age_minutes=latest_news_age,
                    setup_family=technical.setup_family,
                )
            )
    return {profile: tuple(values) for profile, values in opportunities.items()}
