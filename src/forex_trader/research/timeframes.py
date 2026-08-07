from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable


@dataclass(frozen=True, slots=True)
class TimeframePolicy:
    name: str
    context_granularity: str
    execution_granularity: str


BASELINE = TimeframePolicy("baseline_h1_m5", "H1", "M5")

# Public TheForexScalpers examples vary by instrument and article. Treat the
# observed H4/H1 context and M30/M15/M10 execution frames as hypotheses to test,
# not as a proprietary/canonical formula.
PUBLIC_METHOD_CANDIDATES: tuple[TimeframePolicy, ...] = (
    TimeframePolicy("h4_m30", "H4", "M30"),
    TimeframePolicy("h4_m15", "H4", "M15"),
    TimeframePolicy("h4_m10", "H4", "M10"),
    TimeframePolicy("h1_m30", "H1", "M30"),
    TimeframePolicy("h1_m15", "H1", "M15"),
    TimeframePolicy("h1_m10", "H1", "M10"),
    BASELINE,
)


def timeframe_ablation_grid(extra: Iterable[TimeframePolicy] = ()) -> tuple[TimeframePolicy, ...]:
    seen: set[tuple[str, str]] = set()
    result: list[TimeframePolicy] = []
    for policy in (*PUBLIC_METHOD_CANDIDATES, *tuple(extra)):
        key = (policy.context_granularity, policy.execution_granularity)
        if key not in seen:
            seen.add(key)
            result.append(policy)
    return tuple(result)
