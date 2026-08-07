from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

import pytest

from forex_trader.domain.enums import OperatingMode
from forex_trader.research.ablation_runtime import (
    FEATURE_MASKS,
    ResearchAblationRequest,
    ShadowAblationRuntime,
)
from forex_trader.research.ablations import (
    AblationVariant,
    FrozenAblationSnapshot,
    ProspectiveAblationDecision,
)


NOW = datetime(2026, 8, 7, 16, 0, tzinfo=UTC)
HASH = "a" * 64


def snapshot() -> FrozenAblationSnapshot:
    return FrozenAblationSnapshot(
        snapshot_id="snap-1",
        instrument="EUR_USD",
        signal_time=NOW,
        policy_fingerprint="policy-v1",
        payload_hash=HASH,
    )


def decision(request: ResearchAblationRequest) -> ProspectiveAblationDecision:
    snap = request.snapshot
    return ProspectiveAblationDecision(
        snapshot_id=snap.snapshot_id,
        snapshot_payload_hash=snap.payload_hash,
        policy_fingerprint=snap.policy_fingerprint,
        instrument=snap.instrument,
        signal_time=snap.signal_time,
        variant=request.variant,
        tradeable=True,
        setup_family="zone_continuation",
        direction="long",
        score=Decimal("0.8"),
        entry_price=Decimal("1.1000"),
        stop_loss=Decimal("1.0990"),
        take_profit=Decimal("1.1030"),
        rejection_code=None,
    )


def test_feature_masks_disable_exactly_one_component_per_ablation() -> None:
    assert FEATURE_MASKS[AblationVariant.FULL].disabled_components == ()
    assert FEATURE_MASKS[AblationVariant.NO_FUNDAMENTALS].disabled_components == ("fundamentals",)
    assert FEATURE_MASKS[AblationVariant.NO_FLOW].disabled_components == ("flow",)
    assert FEATURE_MASKS[AblationVariant.NO_SESSION].disabled_components == ("session",)
    assert FEATURE_MASKS[AblationVariant.NO_ZONE_QUALITY].disabled_components == ("zone_quality",)
    assert FEATURE_MASKS[AblationVariant.NO_RETEST].disabled_components == ("retest",)


def test_runtime_refuses_paper_or_non_shadow_modes_before_evaluator_runs() -> None:
    called = False

    def evaluator(request: ResearchAblationRequest) -> ProspectiveAblationDecision:
        nonlocal called
        called = True
        return decision(request)

    with pytest.raises(ValueError, match="restricted to shadow mode"):
        ShadowAblationRuntime(evaluator, mode=OperatingMode.PAPER, enable_paper_orders=False)
    with pytest.raises(ValueError, match="cannot enable paper broker writes"):
        ShadowAblationRuntime(evaluator, mode=OperatingMode.SHADOW, enable_paper_orders=True)
    assert called is False


def test_shadow_runtime_evaluates_all_masks_on_same_frozen_snapshot() -> None:
    seen: list[ResearchAblationRequest] = []

    def evaluator(request: ResearchAblationRequest) -> ProspectiveAblationDecision:
        seen.append(request)
        return decision(request)

    runtime = ShadowAblationRuntime(evaluator, mode=OperatingMode.SHADOW, enable_paper_orders=False)
    rows = runtime.collect(snapshot())
    assert tuple(row.variant for row in rows) == tuple(AblationVariant)
    assert tuple(request.variant for request in seen) == tuple(AblationVariant)
    assert all(request.execution_enabled is False for request in seen)
    assert len({request.snapshot.payload_hash for request in seen}) == 1


def test_request_rejects_mask_that_does_not_match_variant() -> None:
    with pytest.raises(ValueError, match="feature mask does not match"):
        ResearchAblationRequest(
            snapshot=snapshot(),
            variant=AblationVariant.NO_FLOW,
            mask=FEATURE_MASKS[AblationVariant.FULL],
        )
