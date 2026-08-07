from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from forex_trader.domain.enums import Direction
from forex_trader.domain.models import Candle
from forex_trader.domain.setup_lifecycle import SetupInstance, SetupLifecycleState, SetupTransition, replay_setup
from forex_trader.domain.zone_features import derive_zone_features
from forex_trader.domain.zones import Zone, ZoneKind

NOW = datetime(2026, 8, 7, 12, 0, tzinfo=UTC)


def test_setup_lifecycle_is_deterministic_and_replayable() -> None:
    setup = SetupInstance.create(
        instrument="EUR_USD",
        setup_family="sweep_reclaim",
        policy_version="v1",
        created_at=NOW,
        anchor_id="zone-1",
    )
    duplicate = SetupInstance.create(
        instrument="EUR_USD",
        setup_family="sweep_reclaim",
        policy_version="v1",
        created_at=NOW,
        anchor_id="zone-1",
    )
    assert setup.setup_id == duplicate.setup_id
    states = [
        SetupLifecycleState.CONTEXT_ELIGIBLE,
        SetupLifecycleState.LOCATION_ARMED,
        SetupLifecycleState.CATALYST_DETECTED,
        SetupLifecycleState.CONFIRMATION_PENDING,
        SetupLifecycleState.CANDIDATE_PRODUCED,
    ]
    transitions: list[SetupTransition] = []
    current = setup
    for index, state in enumerate(states, start=1):
        transition = SetupTransition.create(
            setup_id=setup.setup_id,
            from_state=current.state,
            to_state=state,
            available_at=NOW + timedelta(seconds=index),
            event_id=f"event-{index}",
            reason=state.value,
        )
        transitions.append(transition)
        current = current.apply(transition)
    assert current.terminal
    assert current.state is SetupLifecycleState.CANDIDATE_PRODUCED
    assert replay_setup(setup, reversed(transitions)).state is SetupLifecycleState.CANDIDATE_PRODUCED


def test_setup_lifecycle_rejects_bad_time_state_and_setup() -> None:
    with pytest.raises(ValueError):
        SetupInstance.create(
            instrument="EUR_USD",
            setup_family="x",
            policy_version="v1",
            created_at=datetime(2026, 1, 1),
            anchor_id="a",
        )
    setup = SetupInstance.create(instrument="EUR_USD", setup_family="x", policy_version="v1", created_at=NOW, anchor_id="a")
    with pytest.raises(ValueError):
        SetupTransition.create(
            setup_id=setup.setup_id,
            from_state=SetupLifecycleState.OBSERVING,
            to_state=SetupLifecycleState.CANDIDATE_PRODUCED,
            available_at=NOW,
            event_id="bad",
            reason="skip",
        )
    transition = SetupTransition.create(
        setup_id=setup.setup_id,
        from_state=SetupLifecycleState.OBSERVING,
        to_state=SetupLifecycleState.CONTEXT_ELIGIBLE,
        available_at=NOW + timedelta(seconds=1),
        event_id="ok",
        reason="ok",
    )
    wrong = SetupInstance.create(instrument="GBP_USD", setup_family="x", policy_version="v1", created_at=NOW, anchor_id="a")
    with pytest.raises(ValueError):
        wrong.apply(transition)
    advanced = setup.apply(transition)
    with pytest.raises(ValueError):
        advanced.apply(transition)


def _candles() -> list[Candle]:
    values = [
        ("1.1000", "1.1005", "1.0995", "1.1002"),
        ("1.1002", "1.1006", "1.0998", "1.1001"),
        ("1.1001", "1.1004", "1.0999", "1.1002"),
        ("1.1002", "1.1020", "1.1001", "1.1018"),
        ("1.1021", "1.1030", "1.1020", "1.1028"),
        ("1.1029", "1.1034", "1.1025", "1.1032"),
        ("1.1004", "1.1010", "1.0999", "1.1008"),
        ("1.1010", "1.1035", "1.1009", "1.1031"),
    ]
    return [
        Candle(
            NOW + timedelta(minutes=5 * index),
            Decimal(open_),
            Decimal(high),
            Decimal(low),
            Decimal(close),
            volume=100 + index,
        )
        for index, (open_, high, low, close) in enumerate(values)
    ]


def test_zone_features_expose_raw_attributes_without_reweighting() -> None:
    candles = _candles()
    zone = Zone(
        zone_id="z1",
        kind=ZoneKind.DEMAND,
        proximal=Decimal("1.1002"),
        distal=Decimal("1.0995"),
        origin_index=0,
        created_at=NOW,
        departure_multiple=Decimal("1.8"),
        touches=1,
        penetration=Decimal("0.2"),
        freshness=Decimal("0.5"),
        quality=Decimal("0.7"),
        broken=False,
    )
    features = derive_zone_features(
        zone,
        candles,
        origin_timeframe="m5",
        as_of=candles[-1].time,
        atr_value=Decimal("0.001"),
        higher_timeframe_direction=Direction.LONG,
        flow_alignment=Decimal("0.4"),
        liquidity_distance_atr=Decimal("0.5"),
        event_created=True,
    )
    assert features.zone_id == "z1"
    assert features.origin_timeframe == "M5"
    assert features.departure_atr == Decimal("1.8")
    assert features.higher_timeframe_alignment == Decimal("1")
    assert features.event_created
    model = features.as_model_features()
    assert model["flow_alignment"] == "0.4"
    assert features.age_seconds > 0


def test_zone_features_validate_point_in_time_inputs() -> None:
    zone = Zone("z", ZoneKind.SUPPLY, Decimal("1.1"), Decimal("1.2"), 0, NOW, Decimal("1"), 0, Decimal("0"), Decimal("1"), Decimal("1"), False)
    with pytest.raises(ValueError):
        derive_zone_features(zone, [], origin_timeframe="M5", as_of=NOW, atr_value=Decimal("0.001"))
    with pytest.raises(ValueError):
        derive_zone_features(zone, _candles(), origin_timeframe="M5", as_of=datetime(2026, 1, 1), atr_value=Decimal("0.001"))
    with pytest.raises(ValueError):
        derive_zone_features(zone, _candles(), origin_timeframe="M5", as_of=NOW, atr_value=Decimal("0"))
