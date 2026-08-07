from forex_trader.research.timeframes import TimeframePolicy, timeframe_ablation_grid


def test_grid_contains_public_method_hypotheses_and_baseline() -> None:
    pairs = {(p.context_granularity, p.execution_granularity) for p in timeframe_ablation_grid()}
    assert ("H4", "M30") in pairs
    assert ("H4", "M15") in pairs
    assert ("H4", "M10") in pairs
    assert ("H1", "M5") in pairs


def test_grid_deduplicates_equivalent_policy() -> None:
    grid = timeframe_ablation_grid([TimeframePolicy("duplicate", "H1", "M5")])
    assert sum(p.context_granularity == "H1" and p.execution_granularity == "M5" for p in grid) == 1
