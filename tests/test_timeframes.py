from datetime import timedelta

import pytest

from forex_trader.adapters.synthetic import SyntheticMarketData
from forex_trader.adapters.timeframe import TimeframeMappedMarketData
from forex_trader.config import AppConfig, build_engine
from forex_trader.domain.timeframes import granularity_duration, validate_timeframe_pair
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


def test_supported_research_timeframe_pairs_validate() -> None:
    assert validate_timeframe_pair("m10", "h4") == ("M10", "H4")
    assert granularity_duration("M30") == timedelta(minutes=30)
    with pytest.raises(ValueError, match="lower timeframe"):
        validate_timeframe_pair("M1", "H1")
    with pytest.raises(ValueError, match="higher timeframe"):
        validate_timeframe_pair("M5", "H2")
    with pytest.raises(ValueError, match="unsupported strategy granularity"):
        granularity_duration("D")


def test_timeframe_adapter_maps_semantic_engine_requests() -> None:
    provider = SyntheticMarketData(seed=11, quote_granularity="M15")
    mapped = TimeframeMappedMarketData(
        provider,
        lower_timeframe="M15",
        higher_timeframe="H4",
    )
    lower = mapped.candles("EUR_USD", "M5", 20)
    higher = mapped.candles("EUR_USD", "H1", 20)
    assert lower[-1].time - lower[-2].time == timedelta(minutes=15)
    assert higher[-1].time - higher[-2].time == timedelta(hours=4)
    assert mapped.quote("EUR_USD") == provider.quote("EUR_USD")


def test_config_reads_and_builds_nondefault_timeframe_policy(monkeypatch, tmp_path) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.setenv("FOREX_LOWER_TIMEFRAME", "M15")
    monkeypatch.setenv("FOREX_HIGHER_TIMEFRAME", "H4")
    monkeypatch.setenv("FOREX_DATABASE_PATH", str(tmp_path / "timeframe.db"))
    config = AppConfig.from_env()
    assert config.lower_timeframe == "M15"
    assert config.higher_timeframe == "H4"
    assert config.validate() == []
    engine = build_engine(config)
    assert isinstance(engine.market_data, TimeframeMappedMarketData)
    assert engine.market_data.lower_timeframe == "M15"
    assert engine.market_data.higher_timeframe == "H4"


def test_config_rejects_unresearched_timeframe_pair() -> None:
    errors = AppConfig(lower_timeframe="M1", higher_timeframe="H1").validate()
    assert any("lower timeframe" in error for error in errors)
