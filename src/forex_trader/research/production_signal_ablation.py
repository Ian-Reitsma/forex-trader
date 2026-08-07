from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Mapping, Sequence

from forex_trader.domain.decision_components import DecisionComponentPolicy, PRODUCTION_DECISION_COMPONENTS
from forex_trader.domain.enums import DecisionDisposition, OperatingMode
from forex_trader.domain.fusion import RegimeAwareSignalFusionPolicy
from forex_trader.domain.models import Candle, FundamentalAssessment, Quote
from forex_trader.domain.technicals import assess_technicals
from forex_trader.research.ablation_runtime import FEATURE_MASKS, ResearchAblationRequest
from forex_trader.research.ablations import AblationVariant, FrozenAblationSnapshot, ProspectiveAblationDecision
from forex_trader.research.production_ablation import ProductionAblationAdapter, make_component_hooks


class ProductionSignalAblationEvaluator:
    """Re-run the real production technical/fusion path on one frozen snapshot.

    This evaluator stops before portfolio risk and execution. It has no broker and cannot
    submit orders. The full variant uses the exact default production components; each
    masked variant disables exactly the component declared by ``FEATURE_MASKS``.
    """

    def __init__(self, fusion_policy: RegimeAwareSignalFusionPolicy) -> None:
        self._fusion_policy = fusion_policy

    def evaluate_full(self, snapshot: FrozenAblationSnapshot) -> ProspectiveAblationDecision:
        return self._evaluate(snapshot, AblationVariant.FULL, PRODUCTION_DECISION_COMPONENTS)

    def evaluate_masked(self, request: ResearchAblationRequest) -> ProspectiveAblationDecision:
        if request.variant is AblationVariant.FULL:
            raise ValueError("full variant must use evaluate_full")
        disabled = request.mask.disabled_components
        if disabled != FEATURE_MASKS[request.variant].disabled_components or len(disabled) != 1:
            raise ValueError("research ablation request does not contain the declared one-component mask")
        components = _components_for_variant(request.variant)
        return self._evaluate(request.snapshot, request.variant, components)

    def adapter(self) -> ProductionAblationAdapter:
        hooks = make_component_hooks(
            no_fundamentals=self.evaluate_masked,
            no_flow=self.evaluate_masked,
            no_session=self.evaluate_masked,
            no_zone_quality=self.evaluate_masked,
            no_retest=self.evaluate_masked,
        )
        return ProductionAblationAdapter(
            full_evaluator=self.evaluate_full,
            hooks=hooks,
            mode=OperatingMode.SHADOW,
            enable_paper_orders=False,
        )

    def _evaluate(
        self,
        snapshot: FrozenAblationSnapshot,
        variant: AblationVariant,
        components: DecisionComponentPolicy,
    ) -> ProspectiveAblationDecision:
        lower, higher, quote, fundamental, spread_limit = _load_snapshot(snapshot)
        technical = assess_technicals(
            snapshot.instrument,
            list(lower),
            list(higher),
            components=components,
        )
        if technical.signal_time != snapshot.signal_time:
            raise ValueError(
                f"frozen signal time mismatch: technical={technical.signal_time.isoformat()} "
                f"snapshot={snapshot.signal_time.isoformat()}"
            )
        policy = _clone_policy(self._fusion_policy, components)
        candidate = policy.evaluate(
            technical,
            fundamental,
            quote,
            maximum_spread_pips=spread_limit,
            components=components,
        )
        tradeable = candidate.disposition is DecisionDisposition.TRADE
        return ProspectiveAblationDecision(
            snapshot_id=snapshot.snapshot_id,
            snapshot_payload_hash=snapshot.payload_hash,
            policy_fingerprint=snapshot.policy_fingerprint,
            instrument=snapshot.instrument,
            signal_time=snapshot.signal_time,
            variant=variant,
            tradeable=tradeable,
            setup_family=candidate.setup_family or None,
            direction=candidate.direction.value,
            score=candidate.score,
            entry_price=candidate.entry_price,
            stop_loss=candidate.stop_loss,
            take_profit=candidate.take_profit,
            rejection_code=candidate.rejection_code,
        )


def freeze_production_signal_snapshot(
    *,
    snapshot_id: str,
    policy_fingerprint: str,
    instrument: str,
    lower_candles: Sequence[Candle],
    higher_candles: Sequence[Candle],
    quote: Quote,
    fundamental: FundamentalAssessment,
    maximum_spread_pips: Decimal,
) -> FrozenAblationSnapshot:
    """Freeze the exact pre-risk production inputs needed for paired component reruns."""
    if maximum_spread_pips <= 0:
        raise ValueError("maximum_spread_pips must be positive")
    normalized = instrument.upper()
    if quote.instrument.upper() != normalized or fundamental.instrument.upper() != normalized:
        raise ValueError("snapshot quote/fundamental instruments must match")
    lower = tuple(lower_candles)
    higher = tuple(higher_candles)
    technical = assess_technicals(normalized, list(lower), list(higher))
    payload: dict[str, object] = {
        "schema": "production-signal-ablation-v1",
        "lower_candles": [_candle_payload(item) for item in lower],
        "higher_candles": [_candle_payload(item) for item in higher],
        "quote": _quote_payload(quote),
        "fundamental": _fundamental_payload(fundamental),
        "maximum_spread_pips": str(maximum_spread_pips),
    }
    return FrozenAblationSnapshot.from_payload(
        snapshot_id=snapshot_id,
        instrument=normalized,
        signal_time=technical.signal_time,
        policy_fingerprint=policy_fingerprint,
        payload=payload,
    )


def _components_for_variant(variant: AblationVariant) -> DecisionComponentPolicy:
    if variant is AblationVariant.FULL:
        return PRODUCTION_DECISION_COMPONENTS
    disabled = FEATURE_MASKS[variant].disabled_components
    if len(disabled) != 1:
        raise ValueError(f"variant {variant.value} must disable exactly one component")
    values = {
        "fundamentals": True,
        "flow": True,
        "session": True,
        "zone_quality": True,
        "retest": True,
    }
    values[disabled[0]] = False
    return DecisionComponentPolicy(**values)


def _clone_policy(
    source: RegimeAwareSignalFusionPolicy,
    components: DecisionComponentPolicy,
) -> RegimeAwareSignalFusionPolicy:
    return RegimeAwareSignalFusionPolicy(
        minimum_score=source.minimum_score,
        minimum_fundamental_confidence=source.minimum_fundamental_confidence,
        maximum_spread_pips=source.maximum_spread_pips,
        maximum_quote_signal_gap_seconds=source.maximum_quote_signal_gap_seconds,
        minimum_reward_risk=source.minimum_reward_risk,
        require_fundamentals=source.require_fundamentals and components.fundamentals,
        require_liquidity_sweep=source.require_liquidity_sweep,
        require_displacement=source.require_displacement,
        require_structure_shift=source.require_structure_shift,
        require_entry_confirmed=source.require_entry_confirmed,
        minimum_location_score=source.minimum_location_score if components.zone_quality else Decimal("0"),
        maximum_fundamental_conflict=source.maximum_fundamental_conflict,
        minimum_independent_confirmations=source.minimum_independent_confirmations,
        minimum_independent_sources=source.minimum_independent_sources,
        registry=source.registry,
    )


def _load_snapshot(
    snapshot: FrozenAblationSnapshot,
) -> tuple[tuple[Candle, ...], tuple[Candle, ...], Quote, FundamentalAssessment, Decimal]:
    payload = snapshot.require_payload()
    if payload.get("schema") != "production-signal-ablation-v1":
        raise ValueError("unsupported frozen production signal snapshot schema")
    lower = _load_candles(payload.get("lower_candles"), "lower_candles")
    higher = _load_candles(payload.get("higher_candles"), "higher_candles")
    quote = _load_quote(payload.get("quote"))
    fundamental = _load_fundamental(payload.get("fundamental"))
    spread_limit = Decimal(str(payload.get("maximum_spread_pips")))
    if spread_limit <= 0:
        raise ValueError("frozen maximum_spread_pips must be positive")
    if quote.instrument.upper() != snapshot.instrument.upper() or fundamental.instrument.upper() != snapshot.instrument.upper():
        raise ValueError("frozen payload instrument identity does not match snapshot")
    return lower, higher, quote, fundamental, spread_limit


def _load_candles(value: object, name: str) -> tuple[Candle, ...]:
    if not isinstance(value, list):
        raise ValueError(f"{name} must be an array")
    rows: list[Candle] = []
    for index, raw in enumerate(value):
        item = _mapping(raw, f"{name}[{index}]")
        rows.append(
            Candle(
                time=_datetime(item.get("time"), f"{name}[{index}].time"),
                open=Decimal(str(item.get("open"))),
                high=Decimal(str(item.get("high"))),
                low=Decimal(str(item.get("low"))),
                close=Decimal(str(item.get("close"))),
                volume=int(str(item.get("volume", 0))),
                complete=bool(item.get("complete", True)),
            )
        )
    return tuple(rows)


def _load_quote(value: object) -> Quote:
    item = _mapping(value, "quote")
    return Quote(
        instrument=str(item.get("instrument", "")),
        bid=Decimal(str(item.get("bid"))),
        ask=Decimal(str(item.get("ask"))),
        time=_datetime(item.get("time"), "quote.time"),
        bid_liquidity=_optional_decimal(item.get("bid_liquidity")),
        ask_liquidity=_optional_decimal(item.get("ask_liquidity")),
    )


def _load_fundamental(value: object) -> FundamentalAssessment:
    item = _mapping(value, "fundamental")
    reasons = item.get("reasons", [])
    if not isinstance(reasons, list):
        raise ValueError("fundamental.reasons must be an array")
    return FundamentalAssessment(
        instrument=str(item.get("instrument", "")),
        base_score=Decimal(str(item.get("base_score"))),
        quote_score=Decimal(str(item.get("quote_score"))),
        differential=Decimal(str(item.get("differential"))),
        confidence=Decimal(str(item.get("confidence"))),
        reasons=tuple(str(reason) for reason in reasons),
    )


def _candle_payload(candle: Candle) -> dict[str, object]:
    return {
        "time": candle.time.isoformat(),
        "open": str(candle.open),
        "high": str(candle.high),
        "low": str(candle.low),
        "close": str(candle.close),
        "volume": candle.volume,
        "complete": candle.complete,
    }


def _quote_payload(quote: Quote) -> dict[str, object]:
    return {
        "instrument": quote.instrument,
        "bid": str(quote.bid),
        "ask": str(quote.ask),
        "time": quote.time.isoformat(),
        "bid_liquidity": None if quote.bid_liquidity is None else str(quote.bid_liquidity),
        "ask_liquidity": None if quote.ask_liquidity is None else str(quote.ask_liquidity),
    }


def _fundamental_payload(fundamental: FundamentalAssessment) -> dict[str, object]:
    return {
        "instrument": fundamental.instrument,
        "base_score": str(fundamental.base_score),
        "quote_score": str(fundamental.quote_score),
        "differential": str(fundamental.differential),
        "confidence": str(fundamental.confidence),
        "reasons": list(fundamental.reasons),
    }


def _mapping(value: object, name: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise ValueError(f"{name} must be an object")
    return {str(key): item for key, item in value.items()}


def _datetime(value: object, name: str) -> datetime:
    if value is None:
        raise ValueError(f"{name} is required")
    parsed = datetime.fromisoformat(str(value))
    if parsed.tzinfo is None:
        raise ValueError(f"{name} must be timezone-aware")
    return parsed


def _optional_decimal(value: object) -> Decimal | None:
    return None if value is None else Decimal(str(value))
