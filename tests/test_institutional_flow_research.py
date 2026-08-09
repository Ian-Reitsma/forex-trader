from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from forex_trader.domain.enums import Direction
from forex_trader.ingestion.providers import OrderFlowSnapshot
from forex_trader.research.institutional_flow import (
    InstitutionalFlowFeature,
    assess_institutional_flow,
)

NOW = datetime(2026, 8, 7, 14, 0, tzinfo=UTC)


def _snapshot(
    *,
    observed_at: datetime,
    source: str = "cme_fx_futures",
    delta: str | None = None,
    cvd: str | None = None,
    vwap: str | None = None,
    poc: str | None = None,
    volume: str | None = None,
    absorption: str | None = None,
    depth: str | None = None,
    pressure: str | None = None,
    confidence: str = "0.9",
) -> OrderFlowSnapshot:
    def dec(value: str | None) -> Decimal | None:
        return None if value is None else Decimal(value)

    return OrderFlowSnapshot(
        instrument="EUR_USD",
        observed_at=observed_at,
        source=source,
        delta=dec(delta),
        cumulative_delta=dec(cvd),
        vwap=dec(vwap),
        point_of_control=dec(poc),
        volume_expansion=dec(volume),
        absorption=dec(absorption),
        depth_imbalance=dec(depth),
        directional_pressure=dec(pressure),
        confidence=Decimal(confidence),
    )


def test_bullish_centralized_features_derive_confirmation_without_trusting_vendor_scalar() -> None:
    previous = _snapshot(
        observed_at=NOW - timedelta(seconds=30),
        delta="50",
        cvd="1000",
        confidence="0.9",
    )
    latest = _snapshot(
        observed_at=NOW - timedelta(seconds=5),
        delta="180",
        cvd="1250",
        vwap="1.0990",
        poc="1.0985",
        volume="2.0",
        absorption="0.8",
        depth="0.7",
        pressure="-0.9",  # deliberately conflicts with raw derived components
        confidence="0.9",
    )

    assessment = assess_institutional_flow(
        (previous, latest),
        instrument="EUR_USD",
        as_of=NOW,
        current_price=Decimal("1.1005"),
        prior_price=Decimal("1.1000"),
    )

    assert assessment.directional_pressure > Decimal("0.20")
    assert assessment.direction is Direction.LONG
    assert assessment.reported_directional_pressure == Decimal("-0.9")
    assert any("conflicts" in reason for reason in assessment.reasons)
    assert assessment.confidence < Decimal("0.9")
    features = {item.feature for item in assessment.features}
    assert InstitutionalFlowFeature.DELTA in features
    assert InstitutionalFlowFeature.CVD_CHANGE in features
    assert InstitutionalFlowFeature.ABSORPTION in features
    assert InstitutionalFlowFeature.DEPTH_IMBALANCE in features
    assert InstitutionalFlowFeature.VWAP_LOCATION in features
    assert InstitutionalFlowFeature.POC_LOCATION in features
    assert InstitutionalFlowFeature.VOLUME_EXPANSION in features


def test_cvd_divergence_is_separately_tagged() -> None:
    previous = _snapshot(observed_at=NOW - timedelta(seconds=20), cvd="1000")
    latest = _snapshot(observed_at=NOW - timedelta(seconds=5), cvd="1300", confidence="1")

    assessment = assess_institutional_flow(
        (previous, latest),
        instrument="EUR_USD",
        as_of=NOW,
        current_price=Decimal("1.0990"),
        prior_price=Decimal("1.1000"),
    )

    divergence = [
        item for item in assessment.features if item.feature is InstitutionalFlowFeature.CVD_DIVERGENCE
    ]
    assert len(divergence) == 1
    assert divergence[0].direction is Direction.LONG
    assert "diverges" in divergence[0].reason


def test_future_snapshot_is_excluded_from_point_in_time_assessment() -> None:
    current = _snapshot(
        observed_at=NOW - timedelta(seconds=5),
        delta="100",
        absorption="0.8",
        depth="0.8",
        pressure="0.7",
        confidence="1",
    )
    future = _snapshot(
        observed_at=NOW + timedelta(seconds=1),
        delta="-9999",
        absorption="-1",
        depth="-1",
        pressure="-1",
        confidence="1",
    )

    assessment = assess_institutional_flow(
        (current, future),
        instrument="EUR_USD",
        as_of=NOW,
        current_price=Decimal("1.1000"),
    )

    assert assessment.observed_at == current.observed_at
    assert assessment.directional_pressure > 0


def test_broker_tick_proxy_never_becomes_institutional_confirmation() -> None:
    proxy = _snapshot(
        observed_at=NOW - timedelta(seconds=1),
        source="broker_tick_proxy",
        delta="999",
        absorption="1",
        depth="1",
        pressure="1",
        confidence="1",
    )
    assessment = assess_institutional_flow(
        (proxy,),
        instrument="EUR_USD",
        as_of=NOW,
        current_price=Decimal("1.1000"),
    )
    assert assessment.direction is Direction.FLAT
    assert assessment.confidence == 0
    assert not assessment.eligible_for_confirmation
    assert "not centralized" in assessment.reasons[0]


def test_stale_flow_fails_closed() -> None:
    stale = _snapshot(
        observed_at=NOW - timedelta(seconds=61),
        delta="100",
        absorption="1",
        depth="1",
        confidence="1",
    )
    assessment = assess_institutional_flow(
        (stale,),
        instrument="EUR_USD",
        as_of=NOW,
        current_price=Decimal("1.1000"),
        maximum_age_seconds=Decimal("60"),
    )
    assert assessment.stale
    assert assessment.directional_pressure == 0
    assert assessment.confidence == 0
    assert not assessment.eligible_for_confirmation


def test_missing_snapshot_and_invalid_inputs_fail_closed() -> None:
    missing = assess_institutional_flow(
        (),
        instrument="EUR_USD",
        as_of=NOW,
        current_price=Decimal("1.1000"),
    )
    assert missing.stale
    assert missing.source == "none"
    assert not missing.eligible_for_confirmation

    with pytest.raises(ValueError, match="timezone-aware"):
        assess_institutional_flow(
            (),
            instrument="EUR_USD",
            as_of=datetime(2026, 1, 1),
            current_price=Decimal("1.1"),
        )
    with pytest.raises(ValueError, match="positive"):
        assess_institutional_flow((), instrument="EUR_USD", as_of=NOW, current_price=Decimal("0"))
    with pytest.raises(ValueError, match="non-negative"):
        assess_institutional_flow(
            (_snapshot(observed_at=NOW, volume="-1"),),
            instrument="EUR_USD",
            as_of=NOW,
            current_price=Decimal("1.1"),
        )
