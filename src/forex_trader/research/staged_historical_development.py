from __future__ import annotations

import bisect
import json
from dataclasses import dataclass, replace
from datetime import datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Callable, Iterable, Sequence

from forex_trader.domain.enums import DecisionDisposition, Direction
from forex_trader.domain.macro_history import PointInTimeFundamentalBook
from forex_trader.domain.models import Candle, Quote, TechnicalAssessment, TradeCandidate
from forex_trader.domain.sessions import classify_phase
from forex_trader.domain.strategy import SignalFusionPolicy
from forex_trader.domain.technicals import assess_technicals, pip_size
from forex_trader.domain.zones import ZoneKind
from forex_trader.ingestion.providers import OrderFlowSnapshot
from forex_trader.research.backtest import summarize_trades
from forex_trader.research.institutional_flow import InstitutionalFlowAssessment, assess_institutional_flow
from forex_trader.research.portfolio_risk_replay import (
    HistoricalPortfolioRiskConfig,
    HistoricalPortfolioRiskReplay,
    HistoricalPortfolioRiskReport,
    RiskReplayOpportunity,
)
from forex_trader.research.public_history import HistoricalTick, resample_midpoint_candles
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
        return f"{self.opportunity.instrument}|{self.opportunity.decision_time.isoformat()}|{self.opportunity.entry_time.isoformat()}"


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
    h1_by_instrument: dict[str, tuple[Candle, ...]]

    @classmethod
    def from_ticks(cls, ticks_by_instrument: dict[str, Sequence[HistoricalTick]]) -> "SpotHistoryIndex":
        ordered: dict[str, tuple[HistoricalTick, ...]] = {}
        h1: dict[str, tuple[Candle, ...]] = {}
        for instrument, ticks in ticks_by_instrument.items():
            normalized = instrument.upper()
            values = tuple(sorted(ticks, key=lambda item: item.time))
            ordered[normalized] = values
            h1[normalized] = resample_midpoint_candles(values, timeframe=timedelta(hours=1))
        return cls(ordered, h1)

    def price_at(self, instrument: str, instant: datetime) -> Decimal | None:
        values = self.ticks_by_instrument.get(instrument.upper(), ())
        if not values:
            return None
        times = [item.time for item in values]
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

    @classmethod
    def from_snapshots(cls, snapshots: Iterable[OrderFlowSnapshot]) -> "FlowHistory":
        grouped: dict[str, list[OrderFlowSnapshot]] = {}
        for item in snapshots:
            grouped.setdefault(item.instrument.upper(), []).append(item)
        return cls(
            {
                instrument: tuple(sorted(values, key=lambda item: (item.observed_at, item.source)))
                for instrument, values in grouped.items()
            }
        )

    def assess(
        self,
        execution: CausalExecution,
        *,
        spot_price_at: Callable[[str, datetime], Decimal | None],
    ) -> FlowGateEvidence:
        instrument = execution.opportunity.instrument.upper()
        values = self.by_instrument.get(instrument, ())
        if not values:
            return FlowGateEvidence(False, False, None)
        times = [item.observed_at for item in values]
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
    document = json.loads(Path(path).read_text(encoding="utf-8"))
    payload = document.get("order_flow", []) if isinstance(document, dict) else document
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
    times = [item.time for item in ordered_ticks]
    lower = list(resample_midpoint_candles(ordered_ticks, timeframe=lower_timeframe))
    higher = list(resample_midpoint_candles(ordered_ticks, timeframe=higher_timeframe))
    if len(lower) < 82 or len(higher) < 60:
        return ()
    higher_ready = [item.time + higher_timeframe for item in higher]

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
        structured = _structured_zone_evidence(
            technical,
            candidate,
            lower_window,
            decision_time=decision_time,
        )
        executions.append(CausalExecution(opportunity, candidate, decision_quote, entry_quote, technical, structured))
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
