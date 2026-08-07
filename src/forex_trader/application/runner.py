from __future__ import annotations

import time
from collections.abc import Callable, Iterable

from forex_trader.application.engine import TradingEngine
from forex_trader.domain.models import DecisionTrace


def run_cycles(
    engine: TradingEngine,
    instruments: Iterable[str],
    *,
    execute: bool,
    interval_seconds: float = 60.0,
    max_cycles: int | None = None,
    sleeper: Callable[[float], None] = time.sleep,
) -> list[DecisionTrace]:
    """Run repeated evaluation cycles.

    `max_cycles=None` runs until interrupted. A finite value is useful for smoke tests,
    scheduled jobs, and controlled deployments.
    """
    if interval_seconds < 0:
        raise ValueError("interval_seconds must be non-negative")
    instrument_list = [instrument.upper() for instrument in instruments]
    if not instrument_list:
        raise ValueError("at least one instrument is required")
    traces: list[DecisionTrace] = []
    cycle_number = 0
    while max_cycles is None or cycle_number < max_cycles:
        for instrument in instrument_list:
            traces.append(engine.evaluate(instrument, execute=execute))
        cycle_number += 1
        if max_cycles is None or cycle_number < max_cycles:
            sleeper(interval_seconds)
    return traces
