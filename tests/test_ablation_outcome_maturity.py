from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

import pytest

from forex_trader.domain.models import Candle
from forex_trader.research.ablation_maturity import (
    completed_snapshot_ids,
    mature_ablation_outcomes,
    validate_complete_matured_groups,
)
from forex_trader.research.ablations import (
    AblationVariant,
    MaturedAblationOutcome,
    ProspectiveAblationDecision,
    append_ablation_decisions,
    append_matured_ablation_outcomes,
    load_ablation_decisions,
    load_matured_ablation_outcomes,
)

NOW = datetime(2026, 8, 7, 14, 0, tzinfo=UTC)
HASH = "a" * 64
POLICY = "policy-v0.7.8"


def _row(
    snapshot_id: str,
    variant: AblationVariant,
    *,
    tradeable: bool,
    quote_bid: str = "1.0999",
    quote_ask: str = "1.1001",
) -> ProspectiveAblationDecision:
    return ProspectiveAblationDecision(
        snapshot_id=snapshot_id,
        snapshot_payload_hash=HASH,
        policy_fingerprint=POLICY,
        instrument="EUR_USD",
        signal_time=NOW,
        variant=variant,
        tradeable=tradeable,
        setup_family="zone_liquidity_sweep_reclaim" if tradeable else None,
        direction="long" if tradeable else None,
        score=Decimal("0.80") if tradeable else None,
        entry_price=Decimal("1.1000") if tradeable else None,
        stop_loss=Decimal("1.0990") if tradeable else None,
        take_profit=Decimal("1.1020") if tradeable else None,
        rejection_code=None if tradeable else "SCORE_BELOW_POLICY",
        quote_bid=Decimal(quote_bid),
        quote_ask=Decimal(quote_ask),
    )


def _group(
    snapshot_id: str = "snap-1",
    *,
    tradeable_variants: set[AblationVariant] | None = None,
    quote_bid: str = "1.0999",
    quote_ask: str = "1.1001",
) -> tuple[ProspectiveAblationDecision, ...]:
    enabled = {AblationVariant.FULL} if tradeable_variants is None else tradeable_variants
    return tuple(
        _row(
            snapshot_id,
            variant,
            tradeable=variant in enabled,
            quote_bid=quote_bid,
            quote_ask=quote_ask,
        )
        for variant in AblationVariant
    )


def _candle(
    offset: int,
    *,
    open_price: str = "1.1000",
    high: str = "1.1008",
    low: str = "1.0994",
    close: str = "1.1004",
) -> Candle:
    return Candle(
        NOW + timedelta(minutes=5 * offset),
        Decimal(open_price),
        Decimal(high),
        Decimal(low),
        Decimal(close),
        100,
        True,
    )


def test_prospective_decision_round_trip_retains_quote_and_complete_pairing(tmp_path) -> None:
    path = tmp_path / "ablation-decisions.jsonl"
    rows = _group()
    assert append_ablation_decisions(path, rows) == 6
    loaded = load_ablation_decisions(path)
    assert loaded == rows
    assert {row.quote_bid for row in loaded} == {Decimal("1.0999")}
    assert {row.quote_ask for row in loaded} == {Decimal("1.1001")}


def test_loader_rejects_missing_variant_and_inconsistent_quote(tmp_path) -> None:
    missing = tmp_path / "missing.jsonl"
    append_ablation_decisions(missing, _group()[:-1])
    with pytest.raises(ValueError, match="missing prospective variants"):
        load_ablation_decisions(missing)

    inconsistent = tmp_path / "inconsistent.jsonl"
    rows = list(_group())
    rows[-1] = _row(
        "snap-1",
        AblationVariant.NO_RETEST,
        tradeable=False,
        quote_bid="1.0998",
        quote_ask="1.1002",
    )
    append_ablation_decisions(inconsistent, rows)
    with pytest.raises(ValueError, match="inconsistent prospective identity"):
        load_ablation_decisions(inconsistent)


def test_nontradeable_variants_stay_in_denominator_at_zero_r() -> None:
    outcomes = mature_ablation_outcomes(
        _group(),
        {"EUR_USD": [_candle(0, high="1.1022", low="1.0995", close="1.1018")]},
        maximum_bars=4,
        labeled_at=NOW + timedelta(minutes=5),
    )
    assert len(outcomes) == 6
    by_variant = {row.variant: row for row in outcomes}
    assert by_variant[AblationVariant.FULL].status == "win"
    assert by_variant[AblationVariant.FULL].realized_r > 0
    for variant in AblationVariant:
        if variant is AblationVariant.FULL:
            continue
        assert by_variant[variant].status == "abstain"
        assert by_variant[variant].realized_r == Decimal("0")
        assert by_variant[variant].bars_held == 0


def test_snapshot_is_not_partially_emitted_before_tradeable_timeout_matures() -> None:
    rows = _group()
    pending = mature_ablation_outcomes(
        rows,
        {"EUR_USD": [_candle(0)]},
        maximum_bars=3,
        labeled_at=NOW + timedelta(minutes=5),
    )
    assert pending == ()

    mature = mature_ablation_outcomes(
        rows,
        {"EUR_USD": [_candle(0), _candle(1), _candle(2)]},
        maximum_bars=3,
        labeled_at=NOW + timedelta(minutes=15),
    )
    assert len(mature) == 6
    full = next(row for row in mature if row.variant is AblationVariant.FULL)
    assert full.status == "timeout"
    assert full.bars_held == 3


def test_same_bar_stop_and_target_is_loss_and_flagged_ambiguous() -> None:
    outcomes = mature_ablation_outcomes(
        _group(),
        {
            "EUR_USD": [
                _candle(
                    0,
                    open_price="1.1000",
                    high="1.1024",
                    low="1.0988",
                    close="1.1010",
                )
            ]
        },
        maximum_bars=8,
        labeled_at=NOW + timedelta(minutes=5),
    )
    full = next(row for row in outcomes if row.variant is AblationVariant.FULL)
    assert full.status == "loss"
    assert full.ambiguous_bar is True
    assert full.realized_r < 0


def test_captured_spread_changes_timeout_return_and_slippage_is_preserved() -> None:
    narrow = mature_ablation_outcomes(
        _group("narrow", quote_bid="1.1000", quote_ask="1.1000"),
        {"EUR_USD": [_candle(0, high="1.1008", low="1.0995", close="1.1005")]},
        maximum_bars=1,
        entry_slippage_pips=Decimal("0.10"),
        exit_slippage_pips=Decimal("0.10"),
        labeled_at=NOW + timedelta(minutes=5),
    )
    wide = mature_ablation_outcomes(
        _group("wide", quote_bid="1.0998", quote_ask="1.1002"),
        {"EUR_USD": [_candle(0, high="1.1008", low="1.0995", close="1.1005")]},
        maximum_bars=1,
        entry_slippage_pips=Decimal("0.10"),
        exit_slippage_pips=Decimal("0.10"),
        labeled_at=NOW + timedelta(minutes=5),
    )
    narrow_full = next(row for row in narrow if row.variant is AblationVariant.FULL)
    wide_full = next(row for row in wide if row.variant is AblationVariant.FULL)
    assert narrow_full.status == wide_full.status == "timeout"
    assert narrow_full.realized_r > wide_full.realized_r
    assert narrow_full.estimated_cost_r > 0
    assert wide_full.estimated_cost_r > 0


def test_tradeable_row_without_quote_context_fails_closed() -> None:
    rows = list(_group())
    full = rows[0]
    rows[0] = ProspectiveAblationDecision(
        snapshot_id=full.snapshot_id,
        snapshot_payload_hash=full.snapshot_payload_hash,
        policy_fingerprint=full.policy_fingerprint,
        instrument=full.instrument,
        signal_time=full.signal_time,
        variant=full.variant,
        tradeable=True,
        setup_family=full.setup_family,
        direction=full.direction,
        score=full.score,
        entry_price=full.entry_price,
        stop_loss=full.stop_loss,
        take_profit=full.take_profit,
        rejection_code=full.rejection_code,
    )
    for index in range(1, len(rows)):
        row = rows[index]
        rows[index] = ProspectiveAblationDecision(
            snapshot_id=row.snapshot_id,
            snapshot_payload_hash=row.snapshot_payload_hash,
            policy_fingerprint=row.policy_fingerprint,
            instrument=row.instrument,
            signal_time=row.signal_time,
            variant=row.variant,
            tradeable=row.tradeable,
            setup_family=row.setup_family,
            direction=row.direction,
            score=row.score,
            entry_price=row.entry_price,
            stop_loss=row.stop_loss,
            take_profit=row.take_profit,
            rejection_code=row.rejection_code,
        )
    with pytest.raises(ValueError, match="lacks decision-time quote context"):
        mature_ablation_outcomes(
            rows,
            {"EUR_USD": [_candle(0)]},
            maximum_bars=1,
            labeled_at=NOW + timedelta(minutes=5),
        )


def test_matured_append_resume_contract_accepts_only_complete_groups(tmp_path) -> None:
    outcomes = mature_ablation_outcomes(
        _group(),
        {"EUR_USD": [_candle(0, high="1.1022", low="1.0995", close="1.1018")]},
        maximum_bars=4,
        labeled_at=NOW + timedelta(minutes=5),
    )
    path = tmp_path / "matured.jsonl"
    assert append_matured_ablation_outcomes(path, outcomes) == 6
    loaded = load_matured_ablation_outcomes(path)
    validate_complete_matured_groups(loaded)
    assert completed_snapshot_ids(loaded) == frozenset({"snap-1"})
    assert all(row.label_policy for row in loaded)

    partial = tuple(loaded[:-1])
    with pytest.raises(ValueError, match="missing matured variants"):
        validate_complete_matured_groups(partial)


def test_labeler_script_is_read_only_by_contract() -> None:
    text = Path("scripts/label_ablation_decisions.py").read_text(encoding="utf-8")
    assert "SafeOandaPracticeClient" in text
    assert "candles_between" in text
    assert "place_market_order" not in text
    assert "close_trade" not in text
