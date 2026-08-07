from decimal import Decimal

from forex_trader.domain.promotion import PracticePromotionPolicy, PromotionMetrics


def metrics(**overrides):  # type: ignore[no-untyped-def]
    values = dict(
        decisions=4000,
        trade_candidates=1200,
        submitted_orders=700,
        rejected_orders=2,
        unknown_orders=0,
        closed_trades=600,
        wins=300,
        total_pl=Decimal("1800"),
        gross_profit=Decimal("5200"),
        gross_loss=Decimal("3400"),
        max_drawdown=Decimal("900"),
        median_slippage_pips=Decimal("0.2"),
        active_days=70,
        instruments_traded=5,
        sessions_traded=4,
        unresolved_halts=0,
    )
    values.update(overrides)
    return PromotionMetrics(**values)


def test_promotion_gate_requires_sustained_multi_regime_practice_quality() -> None:
    decision = PracticePromotionPolicy().evaluate(metrics())
    assert decision.ready is True


def test_promotion_gate_rejects_unknown_orders_and_negative_pl() -> None:
    decision = PracticePromotionPolicy().evaluate(metrics(unknown_orders=5, total_pl=Decimal("-10")))
    assert decision.ready is False
    assert any("unknown-order" in reason for reason in decision.reasons)
    assert any("not positive" in reason for reason in decision.reasons)


def test_promotion_gate_rejects_short_campaign_or_unresolved_halt() -> None:
    decision = PracticePromotionPolicy().evaluate(metrics(active_days=14, unresolved_halts=1))
    assert decision.ready is False
    assert any("active days" in reason for reason in decision.reasons)
    assert any("unresolved" in reason for reason in decision.reasons)
