from forex_trader.domain.enums import DecisionDisposition, OrderStatus, RiskDisposition


def test_end_to_end_engine_executes_paper_order(engine) -> None:  # type: ignore[no-untyped-def]
    trace = engine.evaluate("EUR_USD", execute=True)
    assert trace.candidate.disposition is DecisionDisposition.TRADE
    assert trace.risk is not None
    assert trace.risk.disposition is RiskDisposition.GRANTED
    assert trace.order is not None
    assert trace.order.status is OrderStatus.FILLED


def test_engine_does_not_execute_without_flag(engine) -> None:  # type: ignore[no-untyped-def]
    trace = engine.evaluate("EUR_USD", execute=False)
    assert trace.order is None
