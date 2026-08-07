from __future__ import annotations

import json
from dataclasses import replace

import pytest

from forex_trader.application.campaign import PracticeCampaignRunner
from forex_trader.config import AppConfig, build_engine
from forex_trader.research.ablations import AblationVariant
from forex_trader.research.captured_signal_ablation import (
    CapturedProductionSignalAblationEvaluator,
    freeze_captured_signal_snapshot,
    validate_full_against_trace,
)


def _count_provider_calls(engine):  # type: ignore[no-untyped-def]
    provider = engine.market_data.provider
    original_candles = provider.candles
    original_quote = provider.quote
    calls = {"candles": 0, "quotes": 0}

    def candles(instrument, granularity, count):  # type: ignore[no-untyped-def]
        calls["candles"] += 1
        return original_candles(instrument, granularity, count)

    def quote(instrument):  # type: ignore[no-untyped-def]
        calls["quotes"] += 1
        return original_quote(instrument)

    provider.candles = candles
    provider.quote = quote
    return calls


def test_shadow_campaign_captures_six_real_ablation_rows_without_extra_provider_reads(tmp_path) -> None:
    baseline_engine = build_engine(AppConfig(database_path=str(tmp_path / "baseline.db")))
    baseline_calls = _count_provider_calls(baseline_engine)
    PracticeCampaignRunner(
        baseline_engine,
        ["EUR_USD"],
        execute=False,
    ).run_cycle()

    capture_engine = build_engine(AppConfig(database_path=str(tmp_path / "capture.db")))
    capture_calls = _count_provider_calls(capture_engine)
    ablations = tmp_path / "ablations.jsonl"
    runner = PracticeCampaignRunner(
        capture_engine,
        ["EUR_USD"],
        execute=False,
        ablation_evidence_path=ablations,
    )
    report = runner.run_cycle()

    assert capture_calls == baseline_calls
    assert report.instruments_evaluated == 1
    assert report.ablation_snapshots == 1
    assert report.ablation_rows == len(AblationVariant)
    assert report.ablation_errors == 0
    rows = [json.loads(line) for line in ablations.read_text(encoding="utf-8").splitlines()]
    assert [row["variant"] for row in rows] == [variant.value for variant in AblationVariant]
    assert len({row["snapshot_id"] for row in rows}) == 1
    assert len({row["snapshot_payload_hash"] for row in rows}) == 1
    assert len({row["policy_fingerprint"] for row in rows}) == 1


def test_paired_ablation_capture_cannot_coexist_with_campaign_execution(tmp_path) -> None:
    engine = build_engine(AppConfig(database_path=str(tmp_path / "capture.db")))
    with pytest.raises(ValueError, match="shadow campaigns"):
        PracticeCampaignRunner(
            engine,
            ["EUR_USD"],
            execute=True,
            ablation_evidence_path=tmp_path / "ablations.jsonl",
        )


def test_captured_full_replay_matches_actual_trace_and_replays_context_gates(tmp_path) -> None:
    engine = build_engine(AppConfig(database_path=str(tmp_path / "capture.db")))
    trace, inputs = engine.evaluate_with_signal_inputs("EUR_USD")
    evaluator = CapturedProductionSignalAblationEvaluator(engine.fusion_policy)

    normal = freeze_captured_signal_snapshot(
        snapshot_id="capture-normal",
        policy_fingerprint="a" * 64,
        inputs=inputs,
    )
    normal_rows = evaluator.adapter().collect(normal)
    validate_full_against_trace(trace, normal_rows[0])

    rollover = freeze_captured_signal_snapshot(
        snapshot_id="capture-rollover",
        policy_fingerprint="a" * 64,
        inputs=replace(inputs, rollover_blackout=True),
    )
    rollover_rows = {row.variant: row for row in evaluator.adapter().collect(rollover)}
    assert rollover_rows[AblationVariant.FULL].rejection_code == "ROLLOVER_BLACKOUT"
    assert rollover_rows[AblationVariant.FULL].tradeable is False
    assert rollover_rows[AblationVariant.NO_SESSION].rejection_code != "ROLLOVER_BLACKOUT"

    event = freeze_captured_signal_snapshot(
        snapshot_id="capture-event",
        policy_fingerprint="a" * 64,
        inputs=replace(
            inputs,
            event_blackout_reasons=("EUR high-impact release protection window",),
            rollover_blackout=False,
        ),
    )
    event_rows = {row.variant: row for row in evaluator.adapter().collect(event)}
    assert event_rows[AblationVariant.FULL].rejection_code == "EVENT_BLACKOUT"
    assert event_rows[AblationVariant.FULL].tradeable is False


def test_signal_input_capture_rejects_execution(tmp_path) -> None:
    engine = build_engine(AppConfig(database_path=str(tmp_path / "capture.db")))
    with pytest.raises(ValueError, match="shadow evaluation"):
        engine.evaluate_with_signal_inputs("EUR_USD", execute=True)
