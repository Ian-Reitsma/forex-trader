from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from forex_trader.domain.enums import DecisionDisposition, Direction
from forex_trader.domain.models import FundamentalAssessment, Quote, TechnicalAssessment
from forex_trader.domain.strategy import SignalFusionPolicy


def technical(direction: Direction = Direction.LONG) -> TechnicalAssessment:
    return TechnicalAssessment(
        instrument="EUR_USD",
        direction=direction,
        score=Decimal("0.85"),
        atr=Decimal("0.001"),
        rsi=Decimal("55"),
        entry_reference=Decimal("1.1000"),
        stop_reference=Decimal("1.0980") if direction is Direction.LONG else Decimal("1.1020"),
        take_profit_reference=Decimal("1.1040") if direction is Direction.LONG else Decimal("1.0960"),
        reasons=("technical setup",),
        liquidity_sweep=True,
        displacement=True,
        reward_risk=Decimal("2"),
        setup_family="zone_liquidity_sweep_reclaim",
        setup_state="entry_confirmed",
        zone_id="zone-1",
        zone_quality=Decimal("0.8"),
        liquidity_kind="prior_day_low" if direction is Direction.LONG else "prior_day_high",
        liquidity_price=Decimal("1.0990") if direction is Direction.LONG else Decimal("1.1010"),
        liquidity_strength=Decimal("1"),
        structure_shift=True,
        retest_confirmed=True,
        location_score=Decimal("0.8"),
        structural_target=Decimal("1.1040") if direction is Direction.LONG else Decimal("1.0960"),
    )


def fundamental(diff: str = "0.5", confidence: str = "0.9") -> FundamentalAssessment:
    return FundamentalAssessment(
        "EUR_USD",
        Decimal("0.3"),
        Decimal("-0.2"),
        Decimal(diff),
        Decimal(confidence),
        ("fundamental setup",),
    )


def quote(spread: str = "0.0001") -> Quote:
    half = Decimal(spread) / 2
    return Quote("EUR_USD", Decimal("1.1000") - half, Decimal("1.1000") + half, technical().signal_time + timedelta(seconds=1))


def test_fusion_trades_aligned_setup() -> None:
    result = SignalFusionPolicy(minimum_score=Decimal("0.5")).evaluate(technical(), fundamental(), quote())
    assert result.disposition is DecisionDisposition.TRADE
    assert result.direction is Direction.LONG
    assert result.setup_state == "entry_confirmed"
    assert result.rejection_code is None
    assert result.evidence["score_semantics"] == "quality_ranking_not_probability"


def test_fusion_abstains_on_conflict() -> None:
    result = SignalFusionPolicy().evaluate(technical(), fundamental("-0.8"), quote())
    assert result.disposition is DecisionDisposition.ABSTAIN
    assert result.rejection_code == "FUNDAMENTAL_CONFLICT"


def test_admissible_fundamental_strength_does_not_arbitrarily_blend_into_quality_score() -> None:
    policy = SignalFusionPolicy(minimum_score=Decimal("0.5"))
    modest = policy.evaluate(technical(), fundamental("0.10", "0.60"), quote())
    strong = policy.evaluate(technical(), fundamental("0.90", "1.00"), quote())
    assert modest.disposition is DecisionDisposition.TRADE
    assert strong.disposition is DecisionDisposition.TRADE
    assert modest.score == strong.score
    assert modest.fundamental_score != strong.fundamental_score
    assert modest.evidence["score_inputs"] == "technical_structure_location_minus_spread_penalty"


def test_fusion_abstains_on_wide_spread_preserving_setup_score() -> None:
    result = SignalFusionPolicy().evaluate(technical(), fundamental(), quote("0.0005"))
    assert result.disposition is DecisionDisposition.ABSTAIN
    assert result.rejection_code == "SPREAD_TOO_WIDE"
    assert result.score == technical().score


def test_fusion_requires_structure_entry_state_and_fresh_quote() -> None:
    setup = technical()
    missing_shift = TechnicalAssessment(
        **{field: getattr(setup, field) for field in setup.__dataclass_fields__ if field != "structure_shift"},
        structure_shift=False,
    )
    result = SignalFusionPolicy(minimum_score=Decimal("0.5")).evaluate(missing_shift, fundamental(), quote())
    assert result.rejection_code == "NO_STRUCTURE_SHIFT"

    stale_quote = Quote("EUR_USD", Decimal("1.09995"), Decimal("1.10005"), setup.signal_time + timedelta(hours=1))
    result = SignalFusionPolicy(minimum_score=Decimal("0.5")).evaluate(setup, fundamental(), stale_quote)
    assert result.rejection_code == "QUOTE_STALE"


def test_fusion_rejects_low_executable_reward_risk() -> None:
    setup = technical()
    setup = TechnicalAssessment(
        **{
            field: getattr(setup, field)
            for field in setup.__dataclass_fields__
            if field not in {"stop_reference", "take_profit_reference"}
        },
        stop_reference=Decimal("1.0990"),
        take_profit_reference=Decimal("1.1010"),
    )
    result = SignalFusionPolicy(minimum_score=Decimal("0.5")).evaluate(setup, fundamental(), quote())
    assert result.disposition is DecisionDisposition.ABSTAIN
    assert result.rejection_code == "INSUFFICIENT_NET_REWARD"


def test_technical_only_fusion_does_not_add_neutral_fundamental_constant() -> None:
    setup = technical()
    result = SignalFusionPolicy(
        minimum_score=Decimal("0"),
        require_fundamentals=False,
    ).evaluate(setup, fundamental("0", "0"), quote())
    spread_penalty = min(Decimal("0.08"), (Decimal("1") / Decimal("2")) * Decimal("0.04"))
    assert result.score == setup.score - spread_penalty
    assert result.fundamental_score == 0


def test_fusion_rejects_mismatched_instruments() -> None:
    bad_quote = Quote("GBP_USD", Decimal("1.25"), Decimal("1.2501"), datetime.now(UTC))
    with pytest.raises(ValueError, match="must match"):
        SignalFusionPolicy().evaluate(technical(), fundamental(), bad_quote)
