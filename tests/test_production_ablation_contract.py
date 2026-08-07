from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

import pytest

from forex_trader.domain.enums import OperatingMode
from forex_trader.research.ablation_runtime import ResearchAblationRequest
from forex_trader.research.ablations import AblationVariant, FrozenAblationSnapshot, ProspectiveAblationDecision
from forex_trader.research.production_ablation import ProductionAblationAdapter, make_component_hooks

NOW = datetime(2026, 8, 7, 17, 0, tzinfo=UTC)


def snapshot() -> FrozenAblationSnapshot:
    return FrozenAblationSnapshot.from_payload(
        snapshot_id="snap-prod-1",
        instrument="EUR_USD",
        signal_time=NOW,
        policy_fingerprint="policy-v1",
        payload={
            "lower_candles": [{"time": NOW.isoformat(), "close": "1.1000"}],
            "higher_candles": [{"time": NOW.isoformat(), "close": "1.1000"}],
            "quote": {"bid": "1.0999", "ask": "1.1000"},
            "fundamentals": {"base": "EUR", "quote": "USD"},
        },
    )


def row(snap: FrozenAblationSnapshot, variant: AblationVariant) -> ProspectiveAblationDecision:
    return ProspectiveAblationDecision(
        snapshot_id=snap.snapshot_id,
        snapshot_payload_hash=snap.payload_hash,
        policy_fingerprint=snap.policy_fingerprint,
        instrument=snap.instrument,
        signal_time=snap.signal_time,
        variant=variant,
        tradeable=True,
        setup_family="zone_continuation",
        direction="long",
        score=Decimal("0.8"),
        entry_price=Decimal("1.1000"),
        stop_loss=Decimal("1.0990"),
        take_profit=Decimal("1.1030"),
        rejection_code=None,
    )


def full(snap: FrozenAblationSnapshot) -> ProspectiveAblationDecision:
    return row(snap, AblationVariant.FULL)


def masked(request: ResearchAblationRequest) -> ProspectiveAblationDecision:
    return row(request.snapshot, request.variant)


def hooks():  # type: ignore[no-untyped-def]
    return make_component_hooks(
        no_fundamentals=masked,
        no_flow=masked,
        no_session=masked,
        no_zone_quality=masked,
        no_retest=masked,
    )


def test_adapter_requires_complete_explicit_component_hook_set() -> None:
    incomplete = dict(hooks())
    incomplete.pop(AblationVariant.NO_RETEST)
    with pytest.raises(ValueError, match="hooks incomplete"):
        ProductionAblationAdapter(
            full_evaluator=full,
            hooks=incomplete,
            mode=OperatingMode.SHADOW,
            enable_paper_orders=False,
        )


def test_adapter_refuses_non_shadow_or_write_enabled_mode() -> None:
    with pytest.raises(ValueError, match="restricted to shadow mode"):
        ProductionAblationAdapter(
            full_evaluator=full,
            hooks=hooks(),
            mode=OperatingMode.PAPER,
            enable_paper_orders=False,
        )
    with pytest.raises(ValueError, match="cannot enable paper broker writes"):
        ProductionAblationAdapter(
            full_evaluator=full,
            hooks=hooks(),
            mode=OperatingMode.SHADOW,
            enable_paper_orders=True,
        )


def test_full_variant_is_exactly_the_normal_shadow_evaluator() -> None:
    calls: list[str] = []

    def normal(snap: FrozenAblationSnapshot) -> ProspectiveAblationDecision:
        calls.append(snap.payload_hash)
        return row(snap, AblationVariant.FULL)

    adapter = ProductionAblationAdapter(
        full_evaluator=normal,
        hooks=hooks(),
        mode=OperatingMode.SHADOW,
        enable_paper_orders=False,
    )
    snap = snapshot()
    direct = adapter.evaluate_full(snap)
    paired = adapter.collect(snap)[0]
    assert direct == paired
    assert calls == [snap.payload_hash, snap.payload_hash]


def test_each_masked_hook_receives_the_same_snapshot_payload_and_exact_variant() -> None:
    seen: list[tuple[AblationVariant, str, str]] = []

    def evaluator(request: ResearchAblationRequest) -> ProspectiveAblationDecision:
        seen.append((request.variant, request.snapshot.payload_hash, request.snapshot.payload_json))
        return row(request.snapshot, request.variant)

    adapter = ProductionAblationAdapter(
        full_evaluator=full,
        hooks=make_component_hooks(
            no_fundamentals=evaluator,
            no_flow=evaluator,
            no_session=evaluator,
            no_zone_quality=evaluator,
            no_retest=evaluator,
        ),
        mode=OperatingMode.SHADOW,
        enable_paper_orders=False,
    )
    snap = snapshot()
    rows = adapter.collect(snap)
    assert tuple(item.variant for item in rows) == tuple(AblationVariant)
    assert tuple(item[0] for item in seen) == tuple(AblationVariant)[1:]
    assert {item[1] for item in seen} == {snap.payload_hash}
    assert {item[2] for item in seen} == {snap.payload_json}


def test_component_hook_declaration_must_match_variant() -> None:
    from forex_trader.research.production_ablation import ComponentAblationHook

    with pytest.raises(ValueError, match="does not match"):
        ComponentAblationHook(
            variant=AblationVariant.NO_FLOW,
            component="fundamentals",
            evaluator=masked,
        )


def test_full_evaluator_cannot_relabel_or_change_snapshot_identity() -> None:
    snap = snapshot()

    def wrong_variant(candidate: FrozenAblationSnapshot) -> ProspectiveAblationDecision:
        return row(candidate, AblationVariant.NO_FLOW)

    adapter = ProductionAblationAdapter(
        full_evaluator=wrong_variant,
        hooks=hooks(),
        mode=OperatingMode.SHADOW,
        enable_paper_orders=False,
    )
    with pytest.raises(ValueError, match="full variant"):
        adapter.evaluate_full(snap)
