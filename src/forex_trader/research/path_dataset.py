from __future__ import annotations

import json
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from typing import Iterable, Mapping

from forex_trader.domain.models import Candle
from forex_trader.domain.technicals import pip_size
from forex_trader.research.dataset import decision_key
from forex_trader.research.evidence import DecisionEvidence, candidate_from_evidence
from forex_trader.research.phase_d import PhaseDScenario


def load_candle_archive(path: str | Path) -> dict[str, tuple[Candle, ...]]:
    """Load immutable JSONL midpoint/executable candle research data.

    Each row must contain instrument, time, open, high, low, close and may contain
    complete (default true). Duplicate instrument/time rows are rejected rather than
    last-write-wins because silent dataset mutation invalidates paired comparisons.
    """
    file_path = Path(path)
    if not file_path.is_file():
        raise FileNotFoundError(file_path)
    buckets: dict[str, list[Candle]] = {}
    seen: set[tuple[str, datetime]] = set()
    for line_number, raw in enumerate(file_path.read_text(encoding="utf-8").splitlines(), start=1):
        if not raw.strip():
            continue
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise ValueError(f"invalid candle archive JSONL line {line_number}: {exc.msg}") from exc
        if not isinstance(payload, Mapping):
            raise ValueError(f"invalid candle archive JSONL line {line_number}: expected object")
        try:
            instrument = _required_text(payload.get("instrument"), "instrument").upper()
            time = _required_datetime(payload.get("time"), "time")
            candle = Candle(
                time=time,
                open=_required_decimal(payload.get("open"), "open"),
                high=_required_decimal(payload.get("high"), "high"),
                low=_required_decimal(payload.get("low"), "low"),
                close=_required_decimal(payload.get("close"), "close"),
                volume=_optional_decimal(payload.get("volume")),
                complete=_optional_bool(payload.get("complete"), default=True),
            )
        except (TypeError, ValueError) as exc:
            raise ValueError(f"invalid candle archive JSONL line {line_number}: {exc}") from exc
        key = (instrument, time)
        if key in seen:
            raise ValueError(f"duplicate candle archive row at line {line_number}: {instrument} {time.isoformat()}")
        seen.add(key)
        buckets.setdefault(instrument, []).append(candle)
    if not buckets:
        raise ValueError("candle archive contains no records")
    return {
        instrument: tuple(sorted(candles, key=lambda candle: candle.time))
        for instrument, candles in sorted(buckets.items())
    }


def build_phase_d_scenarios(
    decisions: Iterable[DecisionEvidence],
    candles_by_instrument: Mapping[str, Iterable[Candle]],
    *,
    maximum_entry_bars: int,
    maximum_holding_bars: int,
    as_of: datetime | None = None,
) -> tuple[PhaseDScenario, ...]:
    if maximum_entry_bars < 1 or maximum_holding_bars < 1:
        raise ValueError("Phase D horizons must be positive")
    if as_of is not None and as_of.tzinfo is None:
        raise ValueError("as_of must be timezone-aware")
    required_bars = maximum_entry_bars + maximum_holding_bars
    scenarios: list[PhaseDScenario] = []
    for decision in decisions:
        if not decision.is_trade_candidate or decision.signal_time is None:
            continue
        available = tuple(
            candle
            for candle in candles_by_instrument.get(decision.instrument, ())
            if candle.complete
            and candle.time >= decision.signal_time
            and (as_of is None or candle.time <= as_of)
        )
        if len(available) < required_bars:
            continue
        spread_pips = Decimal("0")
        if decision.quote_bid is not None and decision.quote_ask is not None:
            pip = pip_size(decision.instrument)
            if pip <= 0:
                raise ValueError("pip size must be positive")
            spread_pips = max(Decimal("0"), decision.quote_ask - decision.quote_bid) / pip
        scenarios.append(
            PhaseDScenario(
                signal_key=decision_key(decision),
                candidate=candidate_from_evidence(decision),
                future_candles=available[:required_bars],
                spread_pips=spread_pips,
            )
        )
    return tuple(sorted(scenarios, key=_scenario_key))


def _scenario_key(scenario: PhaseDScenario) -> tuple[datetime, str]:
    signal_time = scenario.candidate.signal_time
    if not isinstance(signal_time, datetime):
        raise ValueError("Phase D scenario signal time must be datetime")
    return signal_time, scenario.signal_key


def _optional_decimal(value: object) -> Decimal | None:
    if value is None or value == "":
        return None
    return Decimal(str(value))


def _required_decimal(value: object, name: str) -> Decimal:
    parsed = _optional_decimal(value)
    if parsed is None:
        raise ValueError(f"{name} is required")
    return parsed


def _required_text(value: object, name: str) -> str:
    if value is None:
        raise ValueError(f"{name} is required")
    text = str(value).strip()
    if not text:
        raise ValueError(f"{name} is required")
    return text


def _required_datetime(value: object, name: str) -> datetime:
    if value is None or value == "":
        raise ValueError(f"{name} is required")
    parsed = value if isinstance(value, datetime) else datetime.fromisoformat(str(value))
    if parsed.tzinfo is None:
        raise ValueError(f"{name} must be timezone-aware")
    return parsed


def _optional_bool(value: object, *, default: bool) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    raise ValueError("complete must be boolean")
