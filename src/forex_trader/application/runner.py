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
    on_error: Callable[[str, Exception], None] | None = None,
) -> list[DecisionTrace]:
    """Run repeated evaluation cycles without unbounded continuous-run memory.

    Finite runs return their traces for tests/diagnostics. Continuous operation
    persists each trace in the repository and does not retain an ever-growing list.
    One instrument/provider failure is isolated from the rest of the cycle.
    """
    if interval_seconds < 0:
        raise ValueError("interval_seconds must be non-negative")
    instrument_list = [instrument.upper() for instrument in instruments]
    if not instrument_list:
        raise ValueError("at least one instrument is required")
    traces: list[DecisionTrace] = []
    cycle_number = 0
    while max_cycles is None or cycle_number < max_cycles:
        cycle_started = time.monotonic()
        for instrument in instrument_list:
            try:
                trace = engine.evaluate(instrument, execute=execute)
            except Exception as exc:
                if on_error is not None:
                    on_error(instrument, exc)
                continue
            if max_cycles is not None:
                traces.append(trace)
        cycle_number += 1
        if max_cycles is None or cycle_number < max_cycles:
            elapsed = time.monotonic() - cycle_started
            sleeper(max(0.0, interval_seconds - elapsed) if interval_seconds >= 1 else interval_seconds)
    return traces
