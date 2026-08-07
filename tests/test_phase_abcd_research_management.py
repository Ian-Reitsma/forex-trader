from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from forex_trader.domain.enums import Direction
from forex_trader.domain.position_management import (
    ManagementAction,
    PositionManagementContext,
    RuntimeManagementPolicy,
)
from forex_trader.research.advanced import (
    AttributionRecord,
    EmpiricalOutcomeModel,
    EventReplayScheduler,
    ExperimentManifest,
    PredictionObservation,
    ReplayEvent,
    attribution_expectancy,
    calibration_report,
    compare_ablations,
    expected_net_r,
)
from forex_trader.research.backtest import BacktestTrade, OutcomeStatus

NOW = datetime(2026, 8, 7, 12, 0, tzinfo=UTC)


def trade(r: str, *, bars: int = 3, mfe: str = "1.2", mae: str = "0.4") -> BacktestTrade:
    value = Decimal(r)
    return BacktestTrade(
        instrument="EUR_USD",
        direction=Direction.LONG,
        signal_time=NOW,
        score=Decimal("0.8"),
        status=OutcomeStatus.WIN if value > 0 else OutcomeStatus.LOSS if value < 0 else OutcomeStatus.TIMEOUT,
        r_multiple=value,
        bars_held=bars,
        maximum_favorable_r=Decimal(mfe),
        maximum_adverse_r=Decimal(mae),
    )


def test_event_replay_orders_by_availability_sequence_and_id() -> None:
    events = [
        ReplayEvent("z", "quote", NOW + timedelta(seconds=1), 2, {}),
        ReplayEvent("b", "release", NOW, 2, {}),
        ReplayEvent("a", "calendar", NOW, 2, {}),
        ReplayEvent("c", "quote", NOW, 1, {}),
    ]
    scheduler = EventReplayScheduler(events)
    assert [item.event_id for item in scheduler.events()] == ["c", "a", "b", "z"]
    seen: list[str] = []
    assert scheduler.run(lambda item: seen.append(item.event_id)) == 4
    assert seen == ["c", "a", "b", "z"]
    with pytest.raises(ValueError):
        ReplayEvent("x", "x", datetime(2026, 1, 1), 0, {})
    with pytest.raises(ValueError):
        ReplayEvent("x", "x", NOW, -1, {})


def test_experiment_manifest_is_content_addressed() -> None:
    manifest = ExperimentManifest(
        git_commit="abc",
        policy_fingerprint="policy",
        dataset_checksums={"bars": "123"},
        provider_dataset_versions={"oanda": "v1"},
        feature_versions={"zones": "v2"},
        model_versions={"outcome": "v1"},
        calibration_version="cal-v1",
        cost_model_version="cost-v1",
        random_seed=7,
        period_start=NOW,
        period_end=NOW + timedelta(days=1),
        folds=("train", "holdout"),
        parameters={"score": "0.68"},
    )
    assert len(manifest.manifest_hash) == 64
    assert manifest.manifest_hash == manifest.manifest_hash
    with pytest.raises(ValueError):
        ExperimentManifest("a", "b", {}, {}, {}, {}, "c", "d", 1, NOW, NOW, (), {})


def test_calibration_reports_brier_and_reliability() -> None:
    observations = [
        PredictionObservation(Decimal("0.1"), False),
        PredictionObservation(Decimal("0.2"), False),
        PredictionObservation(Decimal("0.8"), True),
        PredictionObservation(Decimal("1"), True),
    ]
    report = calibration_report(observations, bin_count=5)
    assert report.count == 4
    assert report.brier_score < Decimal("0.1")
    assert report.expected_calibration_error >= 0
    assert report.bins
    with pytest.raises(ValueError):
        PredictionObservation(Decimal("1.1"), True)
    with pytest.raises(ValueError):
        calibration_report([])
    with pytest.raises(ValueError):
        calibration_report(observations, bin_count=1)


def test_empirical_outcome_and_expected_net_value_are_regularized() -> None:
    model = EmpiricalOutcomeModel()
    empty = model.estimate([])
    assert empty.p_target_before_stop == Decimal("0.5")
    sample = model.estimate([trade("1.5"), trade("1.2"), trade("-1")])
    assert Decimal("0") < sample.p_target_before_stop < Decimal("1")
    assert sample.sample_size == 3
    base = expected_net_r(sample, expected_gain_r=Decimal("1.5"))
    expensive = expected_net_r(sample, expected_gain_r=Decimal("1.5"), spread_cost_r=Decimal("0.1"), slippage_cost_r=Decimal("0.1"))
    assert expensive < base
    with pytest.raises(ValueError):
        EmpiricalOutcomeModel(prior_wins=Decimal("0"))
    with pytest.raises(ValueError):
        expected_net_r(sample, expected_gain_r=Decimal("1"), spread_cost_r=Decimal("-0.1"))


def test_ablations_and_attribution_quantify_incremental_value() -> None:
    full = [trade("1"), trade("1"), trade("-1")]
    variants = {
        "no_fundamentals": [trade("1"), trade("-1"), trade("-1")],
        "no_flow": [trade("1"), trade("1"), trade("-1")],
    }
    results = compare_ablations(full, variants)
    assert {item.name for item in results} == {"no_flow", "no_fundamentals"}
    no_fundamentals = next(item for item in results if item.name == "no_fundamentals")
    assert no_fundamentals.delta_expectancy_r < 0

    records = [
        AttributionRecord("sweep", "trend", "london", "EUR_USD", "aligned", "none", "yes", "market", "low", "small", "target", Decimal("1")),
        AttributionRecord("sweep", "range", "new_york", "EUR_USD", "neutral", "none", "no", "market", "high", "small", "stop", Decimal("-1")),
        AttributionRecord("sweep", "trend", "london", "GBP_USD", "aligned", "none", "yes", "market", "low", "small", "target", Decimal("2")),
    ]
    expectancy = attribution_expectancy(records, field="regime")
    assert expectancy["trend"] == Decimal("1.5")
    assert expectancy["range"] == Decimal("-1")
    with pytest.raises(ValueError):
        attribution_expectancy(records, field="r_multiple")


def context(
    *,
    age_minutes: int = 5,
    price: str = "1.1005",
    event_minutes: int | None = None,
    structure_invalidated: bool = False,
    protected: bool = True,
) -> PositionManagementContext:
    event = None if event_minutes is None else NOW + timedelta(minutes=event_minutes)
    return PositionManagementContext(
        instrument="EUR_USD",
        direction=Direction.LONG,
        opened_at=NOW - timedelta(minutes=age_minutes),
        observed_at=NOW,
        entry_price=Decimal("1.1000"),
        current_price=Decimal(price),
        stop_loss=Decimal("1.0990"),
        take_profit=Decimal("1.1030"),
        upcoming_high_impact_event_at=event,
        structure_invalidated=structure_invalidated,
        protection_confirmed=protected,
    )


def test_runtime_management_closes_invalid_or_stale_scalps() -> None:
    policy = RuntimeManagementPolicy()
    assert policy.decide(context(protected=False)).action is ManagementAction.CLOSE
    assert policy.decide(context(structure_invalidated=True)).action is ManagementAction.CLOSE
    assert policy.decide(context(age_minutes=121, price="1.1010")).action is ManagementAction.CLOSE
    assert policy.decide(context(age_minutes=31, price="1.1000")).action is ManagementAction.CLOSE


def test_runtime_management_handles_event_reduction_break_even_and_hold() -> None:
    policy = RuntimeManagementPolicy()
    assert policy.decide(context(price="1.1005", event_minutes=5)).action is ManagementAction.CLOSE
    reduced = policy.decide(context(price="1.1005", event_minutes=20))
    assert reduced.action is ManagementAction.REDUCE and reduced.reduce_fraction == Decimal("0.5")
    break_even = policy.decide(context(price="1.1011"))
    assert break_even.action is ManagementAction.MOVE_PROTECTION
    assert break_even.new_stop_loss == Decimal("1.1000")
    assert policy.decide(context(price="1.1005")).action is ManagementAction.HOLD


def test_runtime_management_context_validation() -> None:
    with pytest.raises(ValueError):
        PositionManagementContext("EUR_USD", Direction.LONG, datetime(2026, 1, 1), NOW, Decimal("1.1"), Decimal("1.1"), Decimal("1.0"), Decimal("1.2"))
    with pytest.raises(ValueError):
        PositionManagementContext("EUR_USD", Direction.LONG, NOW, NOW - timedelta(seconds=1), Decimal("1.1"), Decimal("1.1"), Decimal("1.0"), Decimal("1.2"))
    with pytest.raises(ValueError):
        PositionManagementContext("EUR_USD", Direction.LONG, NOW, NOW, Decimal("1.1"), Decimal("1.1"), Decimal("1.2"), Decimal("1.3"))
    with pytest.raises(ValueError):
        RuntimeManagementPolicy(event_reduce_fraction=Decimal("1"))
