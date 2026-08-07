from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from enum import Enum
from typing import Mapping, cast

from forex_trader.application.engine import TradingEngine


@dataclass(frozen=True, slots=True)
class CampaignUniverseSelection:
    discovered: tuple[str, ...]
    selected: tuple[str, ...]
    excluded: dict[str, str]

    @property
    def excluded_count(self) -> int:
        return len(self.excluded)


def campaign_policy_context(engine: TradingEngine) -> dict[str, object]:
    """Return a secret-free, deterministic, JSON-safe outcome-policy description."""
    fusion = engine.fusion_policy
    risk = engine.risk_policy
    correlation = getattr(risk, "correlation_guard", None)
    market_data = engine.market_data
    raw: dict[str, object] = {
        "schema": "campaign-policy-v1",
        "strategy_version": "zone-liquidity-structure-v0.6",
        "risk_version": "practice-risk-v0.6",
        "engine_class": type(engine).__name__,
        "broker_class": type(engine.broker).__name__,
        "mode": getattr(engine.mode, "value", str(engine.mode)),
        "paper_orders_enabled": bool(engine.enable_paper_orders),
        "timeframes": {
            "lower": getattr(market_data, "lower_timeframe", "semantic-M5"),
            "higher": getattr(market_data, "higher_timeframe", "semantic-H1"),
        },
        "fusion": {
            "minimum_score": fusion.minimum_score,
            "minimum_fundamental_confidence": fusion.minimum_fundamental_confidence,
            "maximum_spread_pips": fusion.maximum_spread_pips,
            "maximum_quote_signal_gap_seconds": fusion.maximum_quote_signal_gap_seconds,
            "minimum_reward_risk": fusion.minimum_reward_risk,
            "require_fundamentals": fusion.require_fundamentals,
            "require_liquidity_sweep": fusion.require_liquidity_sweep,
            "require_displacement": fusion.require_displacement,
            "require_structure_shift": fusion.require_structure_shift,
            "require_entry_confirmed": fusion.require_entry_confirmed,
            "minimum_location_score": fusion.minimum_location_score,
            "maximum_fundamental_conflict": fusion.maximum_fundamental_conflict,
        },
        "risk": {
            "risk_fraction": risk.risk_fraction,
            "max_daily_loss_fraction": risk.max_daily_loss_fraction,
            "max_open_positions": risk.max_open_positions,
            "max_units": risk.max_units,
            "minimum_units": risk.minimum_units,
            "scale_risk_by_score": risk.scale_risk_by_score,
            "max_gross_exposure_fraction": risk.max_gross_exposure_fraction,
            "max_currency_exposure_fraction": risk.max_currency_exposure_fraction,
            "margin_buffer_fraction": risk.margin_buffer_fraction,
            "authorization_ttl_seconds": risk.authorization_ttl_seconds,
        },
        "correlation": None
        if correlation is None
        else {
            "semantic_granularity": correlation.semantic_granularity,
            "lookback": correlation.lookback,
            "minimum_observations": correlation.minimum_observations,
            "maximum_signed_correlation": correlation.maximum_signed_correlation,
            "fail_closed": correlation.fail_closed,
        },
        "maximum_slippage_pips": engine.maximum_slippage_pips,
    }
    return cast(dict[str, object], _jsonable(raw))


def campaign_policy_fingerprint(context: Mapping[str, object]) -> str:
    canonical = json.dumps(_jsonable(dict(context)), sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:24]


def select_campaign_universe(
    engine: TradingEngine,
    instruments: tuple[str, ...] | list[str],
    *,
    require_fundamental_coverage: bool,
    as_of: datetime | None = None,
) -> CampaignUniverseSelection:
    """Filter guaranteed-ineligible pairs before expensive market-data evaluation.

    This is an efficiency preflight only. It never promotes a pair to a trade; TradingEngine
    still performs full quote-time fundamental assessment plus every strategy, context, risk
    and execution check. If fundamentals are required and current point-in-time confidence
    cannot reach the configured minimum, the pair is guaranteed to abstain and an execution
    campaign need not fetch its candle histories and pricing merely to rediscover that fact.
    """
    discovered = tuple(dict.fromkeys(item.strip().upper() for item in instruments if item.strip()))
    if not require_fundamental_coverage:
        return CampaignUniverseSelection(discovered, discovered, {})
    instant = (as_of or datetime.now(UTC)).astimezone(UTC)
    selected: list[str] = []
    excluded: dict[str, str] = {}
    minimum = engine.fusion_policy.minimum_fundamental_confidence
    for instrument in discovered:
        try:
            assessment = engine.fundamentals.assess_pair(instrument, as_of=instant)
        except Exception as exc:
            excluded[instrument] = f"fundamental preflight failed: {type(exc).__name__}: {exc}"
            continue
        if assessment.confidence < minimum:
            reason = next(
                (item for item in assessment.reasons if "missing fundamental" in item.lower()),
                f"fundamental confidence {assessment.confidence} is below {minimum}",
            )
            excluded[instrument] = reason
            continue
        selected.append(instrument)
    return CampaignUniverseSelection(discovered, tuple(selected), excluded)


def _jsonable(value: object) -> object:
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, Mapping):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        return [_jsonable(item) for item in value]
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    return str(value)
