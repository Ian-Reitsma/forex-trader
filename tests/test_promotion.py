from decimal import Decimal

from forex_trader.domain.promotion import PracticePromotionPolicy, PromotionMetrics


def metrics(**overrides):  # type: ignore[no-untyped-def]
    values = dict(
        decisions=1000,
        trade_candidates=200,
        submitted_orders=100,
        rejected_orders=0,
        unknown_orders=0,
        closed_trades=80,
        wins=45,
        total_pl=Decimal("500"),
        gross_profit=Decimal("1200"),
        gross_loss=Decimal("700"),
        max_drawdown=Decimal("300"),
        median_slippage_pips=Decimal("0.2"),
    )
    values.update(overrides)
    return PromotionMetrics(**values)


def test_promotion_gate_requires_sample_and_positive_quality() -> None:
    decision = PracticePromotionPolicy().evaluate(metrics())
    assert decision.ready is True


def test_promotion_gate_rejects_unknown_orders_and_negative_pl() -> None:
    decision = PracticePromotionPolicy().evaluate(
        metrics(unknown_orders=5, total_pl=Decimal("-10"))
    )
    assert decision.ready is False
    assert any("unknown-order" in reason for reason in decision.reasons)
    assert any("not positive" in reason for reason in decision.reasons)
