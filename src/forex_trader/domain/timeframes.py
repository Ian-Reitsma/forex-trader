from __future__ import annotations

from datetime import timedelta
from math import ceil


# These are the timeframe combinations already represented by the repository's
# research grid. Runtime deliberately supports the same policy surface rather than
# exposing arbitrary OANDA granularities that have not been part of strategy research.
LOWER_TIMEFRAMES = frozenset({"M5", "M10", "M15", "M30"})
HIGHER_TIMEFRAMES = frozenset({"H1", "H4"})

_GRANULARITY_SECONDS = {
    "M5": 5 * 60,
    "M10": 10 * 60,
    "M15": 15 * 60,
    "M30": 30 * 60,
    "H1": 60 * 60,
    "H4": 4 * 60 * 60,
}

# The lower-timeframe liquidity engine may need the entire current 5-p.m.-NY FX day
# plus the entire preceding day. Forty-eight clock hours is therefore the minimum raw
# window before weekend/market closures are considered. OANDA's count is a bar count,
# so this deliberately errs on the side of retaining more completed trading history.
MINIMUM_LOWER_HISTORY = timedelta(hours=48)


def granularity_duration(granularity: str) -> timedelta:
    key = granularity.upper()
    try:
        return timedelta(seconds=_GRANULARITY_SECONDS[key])
    except KeyError as exc:
        raise ValueError(f"unsupported strategy granularity: {granularity}") from exc


def bars_for_duration(granularity: str, duration: timedelta) -> int:
    if duration <= timedelta(0):
        raise ValueError("history duration must be positive")
    step = granularity_duration(granularity)
    return max(1, ceil(duration.total_seconds() / step.total_seconds()))


def minimum_lower_history_count(granularity: str) -> int:
    return bars_for_duration(granularity, MINIMUM_LOWER_HISTORY)


def validate_timeframe_pair(lower: str, higher: str) -> tuple[str, str]:
    lower = lower.upper()
    higher = higher.upper()
    if lower not in LOWER_TIMEFRAMES:
        raise ValueError(
            f"lower timeframe {lower} is unsupported; choose one of {sorted(LOWER_TIMEFRAMES)}"
        )
    if higher not in HIGHER_TIMEFRAMES:
        raise ValueError(
            f"higher timeframe {higher} is unsupported; choose one of {sorted(HIGHER_TIMEFRAMES)}"
        )
    if granularity_duration(lower) >= granularity_duration(higher):
        raise ValueError("lower timeframe must be shorter than higher timeframe")
    return lower, higher
