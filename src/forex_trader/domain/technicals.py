from __future__ import annotations

from datetime import timedelta
from decimal import Decimal

from forex_trader.domain.enums import Direction
from forex_trader.domain.instruments import pip_size_for
from forex_trader.domain.liquidity import build_liquidity_map, find_recent_sweep, target_levels
from forex_trader.domain.market_structure import SwingKind, assess_structure, find_swings
from forex_trader.domain.models import Candle, TechnicalAssessment
from forex_trader.domain.orderflow import broker_tick_activity_proxy
from forex_trader.domain.sessions import SessionPhase, classify_phase
from forex_trader.domain.setup import derive_setup_state
from forex_trader.domain.zones import detect_zones, nearest_zone, opposing_zones


def _require(values: list[Decimal], period: int) -> None:
    if len(values) < period:
        raise ValueError(f"need at least {period} values")


def ema(values: list[Decimal], period: int) -> Decimal:
    _require(values, period)
    alpha = Decimal("2") / Decimal(period + 1)
    result = sum(values[:period]) / Decimal(period)
    for value in values[period:]:
        result = value * alpha + result * (Decimal("1") - alpha)
    return result


def atr(candles: list[Candle], period: int = 14) -> Decimal:
    if len(candles) < period + 1:
        raise ValueError(f"need at least {period + 1} candles")
    ranges: list[Decimal] = []
    for previous, current in zip(candles[-period - 1 : -1], candles[-period:], strict=True):
        ranges.append(
            max(
                current.high - current.low,
                abs(current.high - previous.close),
                abs(current.low - previous.close),
            )
        )
    return sum(ranges) / Decimal(period)


def rsi(values: list[Decimal], period: int = 14) -> Decimal:
    if len(values) < period + 1:
        raise ValueError(f"need at least {period + 1} values")
    deltas = [b - a for a, b in zip(values[-period - 1 : -1], values[-period:], strict=True)]
    gains = sum((d for d in deltas if d > 0), Decimal("0")) / Decimal(period)
    losses = sum((-d for d in deltas if d < 0), Decimal("0")) / Decimal(period)
    if losses == 0:
        return Decimal("100")
    relative_strength = gains / losses
    return Decimal("100") - Decimal("100") / (Decimal("1") + relative_strength)


def pip_size(instrument: str) -> Decimal:
    return pip_size_for(instrument)


def assess_technicals(
    instrument: str,
    lower: list[Candle],
    higher: list[Candle],
    *,
    minimum_structural_reward_risk: Decimal = Decimal("1.35"),
) -> TechnicalAssessment:
    """Derive a Forex-Scalper-style setup from location, liquidity and structure.

    The decision hierarchy is intentionally not indicator-first:
    higher-timeframe pivots -> supply/demand location -> declared liquidity sweep ->
    post-sweep structure break -> retest/hold -> structural target. EMA/RSI/ATR and
    broker tick activity remain secondary diagnostics/regime evidence.
    """
    instrument = instrument.upper()
    completed_lower = [c for c in lower if c.complete]
    completed_higher = [c for c in higher if c.complete]
    if len(completed_lower) < 80 or len(completed_higher) < 60:
        raise ValueError("at least 80 lower and 60 higher completed candles are required")
    if minimum_structural_reward_risk <= Decimal("1"):
        raise ValueError("minimum_structural_reward_risk must be greater than 1")

    pip = pip_size_for(instrument)
    lower_closes = [c.close for c in completed_lower]
    higher_closes = [c.close for c in completed_higher]
    current = completed_lower[-1]
    lower_step = current.time - completed_lower[-2].time
    if lower_step <= timedelta(0):
        raise ValueError("lower-timeframe candles must have increasing timestamps")
    # OANDA candle timestamps mark the bar start. A completed-candle signal becomes
    # knowable at bar close, so all freshness/session/expiry logic must use that time.
    signal_time = current.time + lower_step
    current_atr = atr(completed_lower)
    higher_atr = atr(completed_higher)
    current_rsi = rsi(lower_closes)
    h_fast = ema(higher_closes, 20)
    h_slow = ema(higher_closes, 50)
    l_fast = ema(lower_closes, 9)
    l_slow = ema(lower_closes, 21)
    trend_strength = abs(h_fast - h_slow) / max(higher_atr, pip)

    higher_structure = assess_structure(completed_higher)
    direction = higher_structure.direction
    reasons: list[str] = []
    pivot_authority = Decimal("0.15")
    if direction is Direction.LONG:
        reasons.append("higher-timeframe confirmed pivots are HH/HL")
    elif direction is Direction.SHORT:
        reasons.append("higher-timeframe confirmed pivots are LH/LL")
    else:
        if h_fast > h_slow and higher_closes[-1] > h_fast:
            direction = Direction.LONG
            pivot_authority = Decimal("0.07")
            reasons.append("higher-timeframe pivots are inconclusive; bullish EMA regime fallback")
        elif h_fast < h_slow and higher_closes[-1] < h_fast:
            direction = Direction.SHORT
            pivot_authority = Decimal("0.07")
            reasons.append("higher-timeframe pivots are inconclusive; bearish EMA regime fallback")
        else:
            reasons.append("higher-timeframe context is not directional")

    liquidity = build_liquidity_map(completed_lower, pip_size=pip)
    sweep = find_recent_sweep(completed_lower, liquidity, pip_size=pip, max_bars=10)
    if sweep is not None:
        reasons.append(
            f"{sweep.level.kind.value} swept at {sweep.level.price} with strength={sweep.level.strength:.2f}"
        )
    directional_sweep = sweep if sweep is not None and sweep.direction is direction else None

    zones = detect_zones(completed_lower, atr_value=current_atr)
    anchor_price = directional_sweep.extreme if directional_sweep is not None else current.close
    zone = nearest_zone(
        zones,
        direction=direction,
        price=anchor_price,
        maximum_distance=current_atr * Decimal("1.6"),
        minimum_quality=Decimal("0.28"),
    ) if direction is not Direction.FLAT else None
    if zone is not None:
        reasons.append(
            f"fresh {zone.kind.value} zone quality={zone.quality:.2f} touches={zone.touches} penetration={zone.penetration:.2f}"
        )

    structure_shift = False
    retest_confirmed = False
    displacement = False
    shift_reference: Decimal | None = None
    if directional_sweep is not None:
        pre = completed_lower[: directional_sweep.candle_index]
        swings = find_swings(pre, left=2, right=2)
        if direction is Direction.LONG:
            highs = [point for point in swings if point.kind is SwingKind.HIGH]
            shift_reference = highs[-1].price if highs else max(c.high for c in pre[-8:])
            structure_shift = any(
                candle.close > shift_reference
                for candle in completed_lower[directional_sweep.candle_index + 1 :]
            )
        elif direction is Direction.SHORT:
            lows = [point for point in swings if point.kind is SwingKind.LOW]
            shift_reference = lows[-1].price if lows else min(c.low for c in pre[-8:])
            structure_shift = any(
                candle.close < shift_reference
                for candle in completed_lower[directional_sweep.candle_index + 1 :]
            )

        bodies = [abs(c.close - c.open) for c in completed_lower[max(0, directional_sweep.candle_index - 10) : directional_sweep.candle_index]]
        average_body = sum(bodies, Decimal("0")) / Decimal(max(1, len(bodies)))
        post = completed_lower[directional_sweep.candle_index + 1 :]
        for candle in post:
            body = abs(candle.close - candle.open)
            candle_range = max(candle.high - candle.low, pip)
            close_location = (candle.close - candle.low) / candle_range
            if direction is Direction.LONG and candle.close > candle.open and body >= max(current_atr * Decimal("0.35"), average_body * Decimal("1.15")) and close_location >= Decimal("0.60"):
                displacement = True
            if direction is Direction.SHORT and candle.close < candle.open and body >= max(current_atr * Decimal("0.35"), average_body * Decimal("1.15")) and close_location <= Decimal("0.40"):
                displacement = True

        if structure_shift and len(completed_lower) - 1 > directional_sweep.candle_index:
            reclaimed = directional_sweep.level.price
            latest = completed_lower[-1]
            if direction is Direction.LONG:
                held_reclaim = latest.low <= reclaimed + current_atr * Decimal("0.55") and latest.close > reclaimed
                held_shift = shift_reference is not None and latest.low <= shift_reference + current_atr * Decimal("0.35") and latest.close >= shift_reference
                retest_confirmed = (held_reclaim or held_shift) and latest.close >= latest.open
            else:
                held_reclaim = latest.high >= reclaimed - current_atr * Decimal("0.55") and latest.close < reclaimed
                held_shift = shift_reference is not None and latest.high >= shift_reference - current_atr * Decimal("0.35") and latest.close <= shift_reference
                retest_confirmed = (held_reclaim or held_shift) and latest.close <= latest.open
            if not retest_confirmed and displacement:
                if direction is Direction.LONG and latest.close > reclaimed and latest.close >= l_fast:
                    retest_confirmed = True
                if direction is Direction.SHORT and latest.close < reclaimed and latest.close <= l_fast:
                    retest_confirmed = True

    location_score = Decimal("0")
    if zone is not None:
        location_score = zone.quality
    elif directional_sweep is not None:
        location_score = directional_sweep.level.strength * Decimal("0.65")
        reasons.append("no fresh zone overlaps the sweep; using declared-liquidity location with reduced confidence")

    setup = derive_setup_state(
        instrument=instrument,
        direction=direction,
        signal_time=signal_time,
        zone_id=zone.zone_id if zone is not None else None,
        zone_quality=zone.quality if zone is not None else Decimal("0"),
        liquidity_kind=directional_sweep.level.kind.value if directional_sweep is not None else None,
        liquidity_price=directional_sweep.level.price if directional_sweep is not None else None,
        liquidity_strength=directional_sweep.level.strength if directional_sweep is not None else Decimal("0"),
        sweep_index=directional_sweep.candle_index if directional_sweep is not None else None,
        latest_index=len(completed_lower) - 1,
        structure_shift=structure_shift,
        retest_confirmed=retest_confirmed,
        location_score=location_score,
        invalidated=bool(zone and zone.broken),
    )
    reasons.extend(setup.reasons)

    flow = broker_tick_activity_proxy(completed_lower, window=24)
    reasons.extend(flow.reasons)
    phase = classify_phase(signal_time)
    reasons.append(f"session phase={phase.value}")

    stop: Decimal | None = None
    target: Decimal | None = None
    structural_rr = Decimal("0")
    if direction is not Direction.FLAT and directional_sweep is not None:
        buffer = max(pip * Decimal("0.5"), current_atr * Decimal("0.08"))
        if direction is Direction.LONG:
            stop_anchor = directional_sweep.extreme
            if zone is not None:
                stop_anchor = min(stop_anchor, zone.distal)
            stop = stop_anchor - buffer
        else:
            stop_anchor = directional_sweep.extreme
            if zone is not None:
                stop_anchor = max(stop_anchor, zone.distal)
            stop = stop_anchor + buffer

        risk = abs(current.close - stop)
        candidates: list[Decimal] = [level.price for level in target_levels(liquidity, direction=direction, entry=current.close)]
        for opposing in opposing_zones(zones, direction=direction, price=current.close):
            candidates.append(opposing.low if direction is Direction.LONG else opposing.high)
        if direction is Direction.LONG:
            candidates.extend(
                point.price for point in (higher_structure.last_high, higher_structure.prior_high) if point is not None and point.price > current.close
            )
            candidates = sorted(set(candidates))
        else:
            candidates.extend(
                point.price for point in (higher_structure.last_low, higher_structure.prior_low) if point is not None and point.price < current.close
            )
            candidates = sorted(set(candidates), reverse=True)
        for objective in candidates:
            rr = abs(objective - current.close) / max(risk, pip)
            if rr >= minimum_structural_reward_risk:
                target = objective
                structural_rr = rr
                break
        if target is not None:
            reasons.append(f"structural target={target} reward/risk={structural_rr:.2f}")
        else:
            reasons.append("no opposing structural/liquidity target provides sufficient reward/risk")

    score = Decimal("0")
    score += pivot_authority if direction is not Direction.FLAT else Decimal("0")
    score += min(Decimal("0.25"), location_score * Decimal("0.25"))
    if directional_sweep is not None:
        score += directional_sweep.level.strength * Decimal("0.20")
    if structure_shift:
        score += Decimal("0.25")
    if retest_confirmed:
        score += Decimal("0.10")
    if displacement:
        score += Decimal("0.05")
    if flow.direction is direction:
        score += min(Decimal("0.04"), flow.confidence * Decimal("0.12"))
    if phase in {SessionPhase.LONDON_OPEN, SessionPhase.NEW_YORK_OPEN, SessionPhase.LONDON_NEW_YORK_OVERLAP, SessionPhase.LONDON_CONTINUATION}:
        score += Decimal("0.04")
    elif phase is SessionPhase.ASIA:
        score += Decimal("0.02")
    if phase is SessionPhase.ROLLOVER:
        score = min(score, Decimal("0.30"))
        reasons.append("rollover phase suppresses setup quality")
    reasons.append(f"EMA diagnostic H20/H50={h_fast}/{h_slow}; L9/L21={l_fast}/{l_slow}")
    reasons.append(f"RSI diagnostic={current_rsi:.1f}")

    return TechnicalAssessment(
        instrument=instrument,
        direction=direction,
        score=max(Decimal("0"), min(Decimal("1"), score)),
        atr=current_atr,
        rsi=current_rsi,
        entry_reference=current.close,
        stop_reference=stop,
        take_profit_reference=target,
        reasons=tuple(reasons),
        signal_time=signal_time,
        liquidity_sweep=directional_sweep is not None,
        displacement=displacement,
        trend_strength=trend_strength,
        reward_risk=structural_rr,
        setup_family=setup.setup_family,
        setup_state=setup.state.value,
        zone_id=setup.zone_id,
        zone_quality=setup.zone_quality,
        liquidity_kind=setup.liquidity_kind,
        liquidity_price=setup.liquidity_price,
        liquidity_strength=setup.liquidity_strength,
        structure_shift=structure_shift,
        retest_confirmed=retest_confirmed,
        location_score=location_score,
        structural_target=target,
        flow_pressure=flow.directional_pressure,
        flow_source=flow.source_kind,
    )
