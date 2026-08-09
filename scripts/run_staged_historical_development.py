from __future__ import annotations

import argparse
import asyncio
import bisect
import json
import os
from dataclasses import dataclass, replace
from datetime import date, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Callable, Iterable, Sequence, cast

from forex_trader.domain.enums import DecisionDisposition, Direction
from forex_trader.domain.macro_history import PointInTimeFundamentalBook
from forex_trader.domain.models import Candle, Quote, TechnicalAssessment, TradeCandidate, jsonable
from forex_trader.domain.sessions import classify_phase
from forex_trader.domain.strategy import SignalFusionPolicy
from forex_trader.domain.technicals import assess_technicals, pip_size
from forex_trader.domain.zones import ZoneKind
from forex_trader.ingestion.file_providers import JsonEconomicCalendarProvider
from forex_trader.ingestion.providers import OrderFlowSnapshot
from forex_trader.research.backtest import summarize_trades
from forex_trader.research.institutional_flow import InstitutionalFlowAssessment, assess_institutional_flow
from forex_trader.research.portfolio_risk_replay import (
    HistoricalPortfolioRiskConfig,
    HistoricalPortfolioRiskReplay,
    HistoricalPortfolioRiskReport,
    RiskReplayOpportunity,
)
from forex_trader.research.public_history import HistoricalTick, resample_midpoint_candles, utc_range
from forex_trader.research.release_surprise_history import PointInTimeReleaseSurpriseAssembler
from forex_trader.research.resilient_tick_history import ResilientDukascopyHistoryClient
from forex_trader.research.return_reporting import PeriodReturnReport, simulate_period_returns
from forex_trader.research.structured_zones import StructuredZone, detect_structured_zones
from forex_trader.research.tick_backtest import TickBacktestOpportunity, evaluate_candidate_on_ticks

STRUCTURED_ZONE_MINIMUM_QUALITY = Decimal("0.50")
STRUCTURED_ZONE_MAXIMUM_DISTANCE_ATR = Decimal("0.50")
MACRO_MINIMUM_CONFIDENCE = Decimal("0.20")
MACRO_MINIMUM_DIRECTIONAL_SUPPORT = Decimal("0.05")
DEFAULT_RISK_FRACTION = Decimal("0.0015")


@dataclass(frozen=True, slots=True)
class StructuredZoneEvidence:
    available: bool
    aligned: bool
    pattern: str | None
    quality: Decimal
    distance_atr: Decimal | None
    zone_id: str | None


@dataclass(frozen=True, slots=True)
class CausalExecution:
    opportunity: TickBacktestOpportunity
    candidate: TradeCandidate
    decision_quote: Quote
    entry_quote: Quote
    technical: TechnicalAssessment
    structured_zone: StructuredZoneEvidence

    def __post_init__(self) -> None:
        if self.candidate.disposition is not DecisionDisposition.TRADE:
            raise ValueError("causal execution candidate must be tradeable")
        if self.candidate.instrument.upper() != self.opportunity.instrument.upper():
            raise ValueError("candidate and opportunity instruments must match")
        if self.entry_quote.instrument.upper() != self.opportunity.instrument.upper():
            raise ValueError("entry quote and opportunity instruments must match")
        if self.entry_quote.time != self.opportunity.entry_time:
            raise ValueError("entry quote timestamp must equal opportunity entry time")

    @property
    def identity(self) -> str:
        return (
            f"{self.opportunity.instrument}|{self.opportunity.decision_time.isoformat()}|"
            f"{self.opportunity.entry_time.isoformat()}"
        )


@dataclass(frozen=True, slots=True)
class MacroGateEvidence:
    available: bool
    passed: bool
    directional_support: Decimal
    confidence: Decimal


@dataclass(frozen=True, slots=True)
class FlowGateEvidence:
    available: bool
    passed: bool
    assessment: InstitutionalFlowAssessment | None


@dataclass(frozen=True, slots=True)
class StageMetrics:
    status: str
    input_executions: int
    selected_executions: int
    coverage: Decimal
    report: object | None
    period_returns: PeriodReturnReport | None
    reason: str = ""


@dataclass(frozen=True, slots=True)
class StagedDevelopmentResult:
    baseline: tuple[CausalExecution, ...]
    structured_zone: tuple[CausalExecution, ...]
    macro: tuple[CausalExecution, ...]
    flow: tuple[CausalExecution, ...]
    baseline_metrics: StageMetrics
    structured_zone_metrics: StageMetrics
    macro_metrics: StageMetrics
    flow_metrics: StageMetrics
    macro_evidence: dict[str, MacroGateEvidence]
    flow_evidence: dict[str, FlowGateEvidence]


@dataclass(frozen=True, slots=True)
class SpotHistoryIndex:
    ticks_by_instrument: dict[str, tuple[HistoricalTick, ...]]
    times_by_instrument: dict[str, tuple[datetime, ...]]
    h1_by_instrument: dict[str, tuple[Candle, ...]]

    @classmethod
    def from_ticks(cls, ticks_by_instrument: dict[str, Sequence[HistoricalTick]]) -> SpotHistoryIndex:
        ordered: dict[str, tuple[HistoricalTick, ...]] = {}
        times: dict[str, tuple[datetime, ...]] = {}
        h1: dict[str, tuple[Candle, ...]] = {}
        for instrument, ticks in ticks_by_instrument.items():
            normalized = instrument.upper()
            values = tuple(sorted(ticks, key=lambda item: item.time))
            ordered[normalized] = values
            times[normalized] = tuple(item.time for item in values)
            h1[normalized] = resample_midpoint_candles(values, timeframe=timedelta(hours=1))
        return cls(ordered, times, h1)

    def price_at(self, instrument: str, instant: datetime) -> Decimal | None:
        normalized = instrument.upper()
        values = self.ticks_by_instrument.get(normalized, ())
        times = self.times_by_instrument.get(normalized, ())
        if not values or not times:
            return None
        index = bisect.bisect_right(times, instant) - 1
        return None if index < 0 else values[index].mid

    def conversion_rate_at(self, source: str, target: str, instant: datetime) -> Decimal | None:
        source = source.upper()
        target = target.upper()
        if source == target:
            return Decimal("1")
        if target != "USD":
            return None
        direct = self.price_at(f"{source}_USD", instant)
        if direct is not None and direct > 0:
            return direct
        inverse = self.price_at(f"USD_{source}", instant)
        if inverse is not None and inverse > 0:
            return Decimal("1") / inverse
        return None

    def correlation_candles(self, instrument: str, granularity: str, as_of: datetime, count: int) -> list[Candle]:
        if granularity.upper() != "H1":
            return []
        values = self.h1_by_instrument.get(instrument.upper(), ())
        eligible = [item for item in values if item.complete and item.time < as_of]
        return eligible[-count:]


@dataclass(frozen=True, slots=True)
class FlowHistory:
    by_instrument: dict[str, tuple[OrderFlowSnapshot, ...]]
    times_by_instrument: dict[str, tuple[datetime, ...]]

    @classmethod
    def from_snapshots(cls, snapshots: Iterable[OrderFlowSnapshot]) -> FlowHistory:
        grouped: dict[str, list[OrderFlowSnapshot]] = {}
        for item in snapshots:
            grouped.setdefault(item.instrument.upper(), []).append(item)
        ordered = {
            instrument: tuple(sorted(values, key=lambda item: (item.observed_at, item.source)))
            for instrument, values in grouped.items()
        }
        times = {instrument: tuple(item.observed_at for item in values) for instrument, values in ordered.items()}
        return cls(ordered, times)

    def assess(
        self,
        execution: CausalExecution,
        *,
        spot_price_at: Callable[[str, datetime], Decimal | None],
    ) -> FlowGateEvidence:
        instrument = execution.opportunity.instrument.upper()
        values = self.by_instrument.get(instrument, ())
        times = self.times_by_instrument.get(instrument, ())
        if not values or not times:
            return FlowGateEvidence(False, False, None)
        index = bisect.bisect_right(times, execution.opportunity.decision_time)
        if index <= 0:
            return FlowGateEvidence(False, False, None)
        history = values[max(0, index - 12) : index]
        previous = history[-2] if len(history) >= 2 else None
        prior_price = None if previous is None else spot_price_at(instrument, previous.observed_at)
        assessment = assess_institutional_flow(
            history,
            instrument=instrument,
            as_of=execution.opportunity.decision_time,
            current_price=execution.entry_quote.mid,
            prior_price=prior_price,
        )
        passed = assessment.eligible_for_confirmation and assessment.direction is execution.candidate.direction
        return FlowGateEvidence(True, passed, assessment)


def load_normalized_order_flow(path: str | Path) -> tuple[OrderFlowSnapshot, ...]:
    document = cast(object, json.loads(Path(path).read_text(encoding="utf-8")))
    if isinstance(document, dict):
        payload = document.get("order_flow", [])
    else:
        payload = document
    if not isinstance(payload, list):
        raise ValueError("normalized order-flow document must contain an order_flow list")
    snapshots: list[OrderFlowSnapshot] = []
    for raw in payload:
        if not isinstance(raw, dict):
            raise ValueError("order-flow rows must be objects")
        observed_at = datetime.fromisoformat(str(raw["observed_at"]).replace("Z", "+00:00"))
        if observed_at.tzinfo is None:
            raise ValueError("order-flow observed_at must be timezone-aware")

        def optional_decimal(name: str) -> Decimal | None:
            value = raw.get(name)
            return None if value is None else Decimal(str(value))

        snapshots.append(
            OrderFlowSnapshot(
                instrument=str(raw["instrument"]).upper(),
                observed_at=observed_at,
                source=str(raw.get("source") or "unknown"),
                delta=optional_decimal("delta"),
                cumulative_delta=optional_decimal("cumulative_delta"),
                vwap=optional_decimal("vwap"),
                point_of_control=optional_decimal("point_of_control"),
                volume_expansion=optional_decimal("volume_expansion"),
                absorption=optional_decimal("absorption"),
                depth_imbalance=optional_decimal("depth_imbalance"),
                directional_pressure=optional_decimal("directional_pressure"),
                confidence=Decimal(str(raw.get("confidence", "0"))),
            )
        )
    return tuple(snapshots)


def generate_causal_executions(
    *,
    instrument: str,
    ticks: Sequence[HistoricalTick],
    fundamentals: PointInTimeFundamentalBook,
    lower_timeframe: timedelta = timedelta(minutes=5),
    higher_timeframe: timedelta = timedelta(hours=1),
    maximum_holding: timedelta = timedelta(hours=2),
    entry_latency: timedelta = timedelta(milliseconds=500),
    adverse_slippage_pips: Decimal = Decimal("0.10"),
    maximum_decision_quote_age: timedelta = timedelta(seconds=10),
    decision_start: datetime | None = None,
    decision_end: datetime | None = None,
) -> tuple[CausalExecution, ...]:
    if len(ticks) < 2:
        return ()
    if decision_start is not None and decision_start.tzinfo is None:
        raise ValueError("decision_start must be timezone-aware")
    if decision_end is not None and decision_end.tzinfo is None:
        raise ValueError("decision_end must be timezone-aware")
    ordered_ticks = tuple(sorted(ticks, key=lambda item: item.time))
    times = tuple(item.time for item in ordered_ticks)
    lower = list(resample_midpoint_candles(ordered_ticks, timeframe=lower_timeframe))
    higher = list(resample_midpoint_candles(ordered_ticks, timeframe=higher_timeframe))
    if len(lower) < 82 or len(higher) < 60:
        return ()
    higher_ready = tuple(item.time + higher_timeframe for item in higher)

    normalized = instrument.upper()
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
    executions: list[CausalExecution] = []
    for index in range(79, len(lower) - 1):
        signal_candle = lower[index]
        decision_time = signal_candle.time + lower_timeframe
        if decision_start is not None and decision_time < decision_start:
            continue
        if decision_end is not None and decision_time >= decision_end:
            continue
        higher_count = bisect.bisect_right(higher_ready, decision_time)
        if higher_count < 60:
            continue
        decision_index = bisect.bisect_left(times, decision_time)
        if decision_index >= len(ordered_ticks):
            continue
        decision_tick = ordered_ticks[decision_index]
        if decision_tick.time - decision_time > maximum_decision_quote_age:
            continue
        lower_window = lower[max(0, index - 199) : index + 1]
        technical = assess_technicals(
            normalized,
            lower_window,
            higher[max(0, higher_count - 200) : higher_count],
            minimum_structural_reward_risk=Decimal("1.01"),
        )
        fundamental = fundamentals.assess_pair(normalized, as_of=decision_time)
        decision_quote = Quote(normalized, decision_tick.bid, decision_tick.ask, decision_tick.time)
        candidate = policy.evaluate(technical, fundamental, decision_quote)
        if candidate.disposition is not DecisionDisposition.TRADE:
            continue

        entry_index = bisect.bisect_left(times, decision_time + entry_latency)
        if entry_index >= len(ordered_ticks):
            continue
        entry_tick = ordered_ticks[entry_index]
        if entry_tick.time - decision_time > maximum_decision_quote_age:
            continue
        entry_quote = Quote(normalized, entry_tick.bid, entry_tick.ask, entry_tick.time)
        candidate = policy.revalidate_execution(candidate, entry_quote, maximum_spread_pips=Decimal("5"))
        if candidate.disposition is not DecisionDisposition.TRADE:
            continue
        if candidate.entry_price is None or candidate.stop_loss is None or candidate.take_profit is None:
            continue
        reward_risk = abs(candidate.take_profit - candidate.entry_price) / abs(candidate.entry_price - candidate.stop_loss)
        outcome = evaluate_candidate_on_ticks(
            candidate,
            ordered_ticks,
            entry_index=entry_index,
            maximum_holding=maximum_holding,
            adverse_slippage_pips=adverse_slippage_pips,
        )
        opportunity = TickBacktestOpportunity(
            instrument=normalized,
            decision_time=decision_time,
            entry_time=outcome.entry_time,
            exit_time=outcome.exit_time,
            trade=replace(outcome.trade, score=technical.score),
            technical_score=technical.score,
            reward_risk=reward_risk,
            spread_pips=entry_tick.spread / pip_size(normalized),
            displacement=technical.displacement,
            session_phase=classify_phase(decision_time),
            news_directional=Decimal("0"),
            news_confidence=Decimal("0"),
            latest_news_age_minutes=None,
            setup_family=technical.setup_family,
        )
        executions.append(
            CausalExecution(
                opportunity=opportunity,
                candidate=candidate,
                decision_quote=decision_quote,
                entry_quote=entry_quote,
                technical=technical,
                structured_zone=_structured_zone_evidence(
                    technical,
                    candidate,
                    lower_window,
                    decision_time=decision_time,
                ),
            )
        )
    return tuple(executions)


def _structured_zone_evidence(
    technical: TechnicalAssessment,
    candidate: TradeCandidate,
    lower_window: Sequence[Candle],
    *,
    decision_time: datetime,
) -> StructuredZoneEvidence:
    if technical.atr <= 0 or candidate.entry_price is None:
        return StructuredZoneEvidence(False, False, None, Decimal("0"), None, None)
    zones = detect_structured_zones(lower_window, atr_value=technical.atr, as_of=decision_time)
    desired_kind = ZoneKind.DEMAND if candidate.direction is Direction.LONG else ZoneKind.SUPPLY
    candidates = [item for item in zones if item.zone.kind is desired_kind and not item.zone.broken]
    if not candidates:
        return StructuredZoneEvidence(False, False, None, Decimal("0"), None, None)

    def distance(item: StructuredZone) -> Decimal:
        entry = candidate.entry_price
        assert entry is not None
        if item.zone.low <= entry <= item.zone.high:
            return Decimal("0")
        return min(abs(entry - item.zone.low), abs(entry - item.zone.high)) / technical.atr

    selected = min(candidates, key=lambda item: (distance(item), -item.research_quality, -item.zone.freshness))
    distance_atr = distance(selected)
    aligned = (
        selected.research_quality >= STRUCTURED_ZONE_MINIMUM_QUALITY
        and distance_atr <= STRUCTURED_ZONE_MAXIMUM_DISTANCE_ATR
    )
    return StructuredZoneEvidence(
        True,
        aligned,
        selected.pattern.value,
        selected.research_quality,
        distance_atr,
        selected.zone.zone_id,
    )


def enforce_nonoverlap(executions: Iterable[CausalExecution]) -> tuple[CausalExecution, ...]:
    selected: list[CausalExecution] = []
    available_after: dict[str, datetime] = {}
    for item in sorted(executions, key=lambda value: (value.opportunity.decision_time, value.opportunity.instrument)):
        instrument = item.opportunity.instrument.upper()
        if item.opportunity.entry_time < available_after.get(instrument, item.opportunity.entry_time):
            continue
        selected.append(item)
        available_after[instrument] = item.opportunity.exit_time
    return tuple(selected)


def macro_gate(execution: CausalExecution, fundamentals: PointInTimeFundamentalBook) -> MacroGateEvidence:
    instrument = execution.opportunity.instrument.upper()
    base, quote = instrument.split("_", maxsplit=1)
    as_of = execution.opportunity.decision_time
    base_state = fundamentals.get(base, as_of=as_of)
    quote_state = fundamentals.get(quote, as_of=as_of)
    if base_state is None or quote_state is None:
        return MacroGateEvidence(False, False, Decimal("0"), Decimal("0"))
    assessment = fundamentals.assess_pair(instrument, as_of=as_of, maximum_age=timedelta(days=14))
    directional = assessment.differential if execution.candidate.direction is Direction.LONG else -assessment.differential
    passed = assessment.confidence >= MACRO_MINIMUM_CONFIDENCE and directional >= MACRO_MINIMUM_DIRECTIONAL_SUPPORT
    return MacroGateEvidence(True, passed, directional, assessment.confidence)


def stage_metrics(
    values: Sequence[CausalExecution],
    *,
    input_count: int,
    period_start: datetime,
    period_end: datetime,
    status: str = "available",
    reason: str = "",
) -> StageMetrics:
    coverage = Decimal("0") if input_count <= 0 else Decimal(len(values)) / Decimal(input_count)
    if status != "available":
        return StageMetrics(status, input_count, len(values), coverage, None, None, reason)
    opportunities = tuple(item.opportunity for item in values)
    report = summarize_trades([item.opportunity.trade for item in values])
    period_returns = simulate_period_returns(
        opportunities,
        period_start=period_start,
        period_end=period_end,
        risk_fraction_per_trade=DEFAULT_RISK_FRACTION,
    )
    return StageMetrics(status, input_count, len(values), coverage, report, period_returns, reason)


def evaluate_stages(
    executions: Sequence[CausalExecution],
    *,
    period_start: datetime,
    period_end: datetime,
    macro_book: PointInTimeFundamentalBook | None = None,
    flow_history: FlowHistory | None = None,
    spot_price_at: Callable[[str, datetime], Decimal | None] | None = None,
) -> StagedDevelopmentResult:
    baseline = enforce_nonoverlap(executions)
    zones = tuple(item for item in baseline if item.structured_zone.aligned)
    macro_evidence: dict[str, MacroGateEvidence] = {}
    flow_evidence: dict[str, FlowGateEvidence] = {}

    if macro_book is None:
        macro_values: tuple[CausalExecution, ...] = ()
        macro_metrics = stage_metrics(
            macro_values,
            input_count=len(zones),
            period_start=period_start,
            period_end=period_end,
            status="unavailable",
            reason="no real point-in-time consensus/actual release archive supplied",
        )
    else:
        for item in zones:
            macro_evidence[item.identity] = macro_gate(item, macro_book)
        macro_values = tuple(item for item in zones if macro_evidence[item.identity].passed)
        available_count = sum(value.available for value in macro_evidence.values())
        macro_metrics = stage_metrics(
            macro_values,
            input_count=len(zones),
            period_start=period_start,
            period_end=period_end,
            status="available" if available_count else "unavailable",
            reason="" if available_count else "macro archive supplied but no pair-complete PIT release state covered staged executions",
        )

    flow_input = macro_values if macro_metrics.status == "available" else zones
    if flow_history is None or spot_price_at is None:
        flow_values: tuple[CausalExecution, ...] = ()
        flow_metrics = stage_metrics(
            flow_values,
            input_count=len(flow_input),
            period_start=period_start,
            period_end=period_end,
            status="unavailable",
            reason="no real centralized futures/order-flow archive supplied",
        )
    else:
        for item in flow_input:
            flow_evidence[item.identity] = flow_history.assess(item, spot_price_at=spot_price_at)
        flow_values = tuple(item for item in flow_input if flow_evidence[item.identity].passed)
        available_count = sum(value.available for value in flow_evidence.values())
        flow_metrics = stage_metrics(
            flow_values,
            input_count=len(flow_input),
            period_start=period_start,
            period_end=period_end,
            status="available" if available_count else "unavailable",
            reason="" if available_count else "centralized flow archive supplied but no PIT snapshot covered staged executions",
        )

    return StagedDevelopmentResult(
        baseline=baseline,
        structured_zone=zones,
        macro=macro_values,
        flow=flow_values,
        baseline_metrics=stage_metrics(
            baseline,
            input_count=len(baseline),
            period_start=period_start,
            period_end=period_end,
        ),
        structured_zone_metrics=stage_metrics(
            zones,
            input_count=len(baseline),
            period_start=period_start,
            period_end=period_end,
        ),
        macro_metrics=macro_metrics,
        flow_metrics=flow_metrics,
        macro_evidence=macro_evidence,
        flow_evidence=flow_evidence,
    )


def replay_production_portfolio_risk(
    values: Sequence[CausalExecution],
    *,
    spot_history: SpotHistoryIndex,
    config: HistoricalPortfolioRiskConfig = HistoricalPortfolioRiskConfig(),
) -> HistoricalPortfolioRiskReport:
    opportunities = tuple(
        RiskReplayOpportunity(
            candidate=item.candidate,
            quote=item.entry_quote,
            trade=item.opportunity.trade,
            entry_time=item.opportunity.entry_time,
            exit_time=item.opportunity.exit_time,
        )
        for item in values
    )
    replay = HistoricalPortfolioRiskReplay(
        config=config,
        mark_price_at=spot_history.price_at,
        conversion_rate_at=spot_history.conversion_rate_at,
        correlation_candle_loader=spot_history.correlation_candles,
    )
    return replay.run(opportunities)


def _existing_path(explicit: str | None, env_name: str) -> Path | None:
    raw = explicit or os.getenv(env_name)
    if not raw:
        return None
    path = Path(raw)
    if not path.exists():
        raise FileNotFoundError(f"{env_name} path does not exist: {path}")
    return path


def _macro_book(
    path: Path | None,
    *,
    history_start: datetime,
    end: datetime,
) -> tuple[PointInTimeFundamentalBook | None, dict[str, object]]:
    if path is None:
        return None, {
            "status": "unavailable",
            "reason": "no normalized real point-in-time economic-calendar/consensus archive supplied",
            "records": 0,
            "unmatched_actuals": 0,
        }
    provider = JsonEconomicCalendarProvider(path)
    metadata = provider.release_metadata()
    consensus = provider.consensus_snapshots(start=history_start, end=end)
    actuals = provider.release_actuals(start=history_start, end=end)
    assembled = PointInTimeReleaseSurpriseAssembler(metadata, consensus, actuals).assemble()
    observations = assembled.macro_observations()
    return PointInTimeFundamentalBook(observations), {
        "status": "available" if observations else "unavailable",
        "source": str(path),
        "metadata": len(metadata),
        "consensus_snapshots": len(consensus),
        "actual_releases": len(actuals),
        "records": len(assembled.records),
        "unmatched_actuals": len(assembled.unmatched_actuals),
        "complete": assembled.complete,
        "unmatched_examples": [
            {
                "currency": item.actual.currency,
                "indicator": item.actual.indicator,
                "available_at": item.actual.available_at,
                "reason": item.reason,
            }
            for item in assembled.unmatched_actuals[:10]
        ],
    }


def _flow_history(path: Path | None) -> tuple[FlowHistory | None, dict[str, object]]:
    if path is None:
        return None, {
            "status": "unavailable",
            "reason": "no normalized real centralized futures/order-flow archive supplied",
            "snapshots": 0,
        }
    snapshots = load_normalized_order_flow(path)
    centralized = tuple(
        item for item in snapshots if item.source.strip().lower() not in {"", "none", "broker_tick_proxy"}
    )
    if not centralized:
        return None, {
            "status": "unavailable",
            "source": str(path),
            "reason": "order-flow archive contained no eligible centralized source snapshots",
            "snapshots": len(snapshots),
            "centralized_snapshots": 0,
        }
    return FlowHistory.from_snapshots(centralized), {
        "status": "available",
        "source": str(path),
        "snapshots": len(snapshots),
        "centralized_snapshots": len(centralized),
        "sources": sorted({item.source for item in centralized}),
    }


def _risk_selected_ids(report: HistoricalPortfolioRiskReport) -> set[object]:
    return {item.candidate.candidate_id for item in report.admitted_opportunities}


async def run(args: argparse.Namespace) -> dict[str, object]:
    start_date = date.fromisoformat(args.start)
    end_date = date.fromisoformat(args.end)
    start, end = utc_range(start_date, end_date)
    if end <= start:
        raise ValueError("development end must be after start")
    instruments = tuple(item.strip().upper() for item in args.instruments.split(",") if item.strip())
    if not instruments:
        raise ValueError("at least one instrument is required")
    history_start = start - timedelta(days=args.warmup_days)
    cache_dir = Path(args.cache_dir)
    cache_dir.mkdir(parents=True, exist_ok=True)

    ticks_by_instrument: dict[str, tuple[HistoricalTick, ...]] = {}
    executions: list[CausalExecution] = []
    empty_fundamentals = PointInTimeFundamentalBook()
    per_instrument: dict[str, object] = {}
    for instrument in instruments:
        history = ResilientDukascopyHistoryClient(
            cache_dir=cache_dir / "dukascopy",
            max_concurrency=args.concurrency_per_pair,
        )
        ticks = await history.ticks(instrument, history_start, end)
        ticks_by_instrument[instrument] = ticks
        generated = generate_causal_executions(
            instrument=instrument,
            ticks=ticks,
            fundamentals=empty_fundamentals,
            maximum_holding=timedelta(minutes=args.maximum_holding_minutes),
            entry_latency=timedelta(milliseconds=args.entry_latency_ms),
            adverse_slippage_pips=Decimal(args.slippage_pips),
            decision_start=start,
            decision_end=end,
        )
        executions.extend(generated)
        per_instrument[instrument] = {
            "history_ticks_including_warmup": len(ticks),
            "generated_causal_executions": len(generated),
        }

    spot = SpotHistoryIndex.from_ticks(ticks_by_instrument)
    economic_path = _existing_path(args.economic_calendar_path, "FOREX_ECONOMIC_CALENDAR_PATH")
    order_flow_path = _existing_path(args.order_flow_path, "FOREX_ORDER_FLOW_PATH")
    macro_book, macro_source = _macro_book(economic_path, history_start=history_start, end=end)
    flow_history, flow_source = _flow_history(order_flow_path)

    staged = evaluate_stages(
        executions,
        period_start=start,
        period_end=end,
        macro_book=macro_book,
        flow_history=flow_history,
        spot_price_at=spot.price_at,
    )

    if staged.flow_metrics.status == "available":
        risk_input_stage = "centralized_flow"
        risk_input = staged.flow
    elif staged.macro_metrics.status == "available":
        risk_input_stage = "pit_macro_surprise"
        risk_input = staged.macro
    elif staged.structured_zone:
        risk_input_stage = "structured_zone"
        risk_input = staged.structured_zone
    else:
        risk_input_stage = "legacy_technical"
        risk_input = staged.baseline

    risk_config = HistoricalPortfolioRiskConfig(
        starting_balance=Decimal(args.starting_balance),
        risk_fraction=Decimal(args.risk_fraction),
    )
    risk_report = replay_production_portfolio_risk(risk_input, spot_history=spot, config=risk_config)
    admitted_ids = _risk_selected_ids(risk_report)
    risk_selected = tuple(item for item in risk_input if item.candidate.candidate_id in admitted_ids)
    risk_metrics = stage_metrics(
        risk_selected,
        input_count=len(risk_input),
        period_start=start,
        period_end=end,
    )

    strict_pipeline = ["legacy_technical", "structured_zone"]
    if staged.macro_metrics.status == "available":
        strict_pipeline.append("pit_macro_surprise")
        if staged.flow_metrics.status == "available":
            strict_pipeline.append("centralized_flow")
    strict_pipeline_complete = staged.macro_metrics.status == "available" and staged.flow_metrics.status == "available"

    return {
        "schema_version": "staged-historical-development-v1",
        "research_role": "development-only component ablation; no validation/proof claim",
        "period": {
            "development_start": start,
            "development_end_exclusive": end,
            "price_warmup_start": history_start,
            "reserved_future_validation": "NOT_OPENED_BY_THIS_RUN",
        },
        "instruments": instruments,
        "frozen_before_outcomes": {
            "structured_zone_minimum_quality": STRUCTURED_ZONE_MINIMUM_QUALITY,
            "structured_zone_maximum_distance_atr": STRUCTURED_ZONE_MAXIMUM_DISTANCE_ATR,
            "macro_minimum_confidence": MACRO_MINIMUM_CONFIDENCE,
            "macro_minimum_directional_support": MACRO_MINIMUM_DIRECTIONAL_SUPPORT,
            "flow_confirmation": "existing InstitutionalFlowAssessment.eligible_for_confirmation plus direction match",
            "risk_fraction": Decimal(args.risk_fraction),
            "starting_balance": Decimal(args.starting_balance),
        },
        "execution_assumptions": {
            "price_source": "Dukascopy first-party BI5 historical best bid/ask",
            "feature_bars": "M5/H1 midpoint bars derived from the same PIT tick archive",
            "entry_latency_ms": args.entry_latency_ms,
            "adverse_slippage_pips_each_side": args.slippage_pips,
            "maximum_holding_minutes": args.maximum_holding_minutes,
            "same_causal_executions_across_component_filters": True,
            "broker_tick_proxy_allowed_as_institutional_flow": False,
        },
        "per_instrument": per_instrument,
        "external_data": {"pit_macro": macro_source, "centralized_flow": flow_source},
        "stages": {
            "legacy_technical": jsonable(staged.baseline_metrics),
            "structured_zone": jsonable(staged.structured_zone_metrics),
            "pit_macro_surprise": jsonable(staged.macro_metrics),
            "centralized_flow": jsonable(staged.flow_metrics),
            "production_portfolio_risk": {
                "input_stage": risk_input_stage,
                "metrics": jsonable(risk_metrics),
                "risk_report": jsonable(risk_report),
            },
        },
        "strict_pipeline": {
            "completed_components": strict_pipeline,
            "complete_through_real_flow": strict_pipeline_complete,
            "stopped_reason": "" if strict_pipeline_complete else (
                "missing real PIT macro archive"
                if staged.macro_metrics.status != "available"
                else "missing real centralized flow archive"
            ),
        },
        "coverage_counts": {
            "raw_generated": len(executions),
            "legacy_nonoverlap": len(staged.baseline),
            "structured_zone": len(staged.structured_zone),
            "macro": len(staged.macro),
            "flow": len(staged.flow),
            "risk_input": len(risk_input),
            "risk_admitted": len(risk_selected),
        },
        "notes": [
            "April-May 2026 sealed tape is not read or used by this development run.",
            "May-August 2026 prior development tape is not used for threshold selection in this run.",
            "Missing consensus or centralized-flow data fails closed and is reported as unavailable; no proxy substitution is allowed.",
            "The portfolio-risk stage calls the production EnhancedRiskPolicy with causal account/open-position state and H1 correlation history.",
        ],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Run frozen staged Forex Scalper component ablation on real historical FX ticks.")
    parser.add_argument("--instruments", default="EUR_USD,GBP_USD,USD_JPY")
    parser.add_argument("--start", default="2026-01-05")
    parser.add_argument("--end", default="2026-04-01")
    parser.add_argument("--warmup-days", type=int, default=14)
    parser.add_argument("--cache-dir", default=".cache/forex-trader/public-history")
    parser.add_argument("--economic-calendar-path")
    parser.add_argument("--order-flow-path")
    parser.add_argument("--concurrency-per-pair", type=int, default=12)
    parser.add_argument("--maximum-holding-minutes", type=int, default=120)
    parser.add_argument("--entry-latency-ms", type=int, default=500)
    parser.add_argument("--slippage-pips", default="0.10")
    parser.add_argument("--starting-balance", default="100000")
    parser.add_argument("--risk-fraction", default=str(DEFAULT_RISK_FRACTION))
    parser.add_argument("--output", default="artifacts/staged-historical-development-v1.json")
    args = parser.parse_args()
    if args.warmup_days < 7:
        raise SystemExit("--warmup-days must be at least 7")
    if args.maximum_holding_minutes <= 0 or args.entry_latency_ms < 0 or Decimal(args.slippage_pips) < 0:
        raise SystemExit("holding time must be positive; latency/slippage cannot be negative")
    report = asyncio.run(run(args))
    rendered = json.dumps(jsonable(report), indent=2, sort_keys=True)
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(rendered + "\n", encoding="utf-8")
    print(rendered)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
