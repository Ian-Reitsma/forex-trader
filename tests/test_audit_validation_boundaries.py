from __future__ import annotations

import json
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from forex_trader.domain.enums import Direction
from forex_trader.domain.macro_factor_risk import MacroFactorClusterGuard, default_macro_factor_map
from forex_trader.domain.models import Candle
from forex_trader.domain.portfolio import OpenPosition
from forex_trader.ingestion.providers import OrderFlowSnapshot
from forex_trader.research.flow_strategies import (
    FlowDivergenceResearchPolicy,
    ResearchFlowState,
    VwapRepositioningResearchPolicy,
)
from forex_trader.research.technical_annotation import (
    BinaryTechnicalLabel,
    TechnicalAdjudication,
    TechnicalAnnotationBatch,
    TechnicalDirectionLabel,
    TechnicalGroundTruthLabel,
    TechnicalReviewerSubmission,
    TechnicalWindow,
    build_blinded_technical_batch,
    finalize_technical_labels,
    label_payload,
    split_technical_calibration_holdout,
    technical_batch_from_payload,
)

NOW = datetime(2026, 8, 7, 14, 0, tzinfo=UTC)


def _candles(*, count: int = 8, complete: bool = True) -> tuple[Candle, ...]:
    return tuple(
        Candle(
            time=NOW - timedelta(hours=2) + timedelta(minutes=5 * index),
            open=Decimal("1.1000") + Decimal(index) * Decimal("0.0001"),
            high=Decimal("1.1003") + Decimal(index) * Decimal("0.0001"),
            low=Decimal("1.0998") + Decimal(index) * Decimal("0.0001"),
            close=Decimal("1.1001") + Decimal(index) * Decimal("0.0001"),
            volume=100 + index,
            complete=complete,
        )
        for index in range(count)
    )


def _window(index: int = 0) -> TechnicalWindow:
    shifted = tuple(replace(candle, time=candle.time + timedelta(days=index)) for candle in _candles())
    return TechnicalWindow("EUR_USD", "M5", shifted)


def _label(direction: TechnicalDirectionLabel = TechnicalDirectionLabel.LONG) -> TechnicalGroundTruthLabel:
    return TechnicalGroundTruthLabel(
        BinaryTechnicalLabel.PRESENT,
        BinaryTechnicalLabel.PRESENT,
        BinaryTechnicalLabel.PRESENT,
        BinaryTechnicalLabel.PRESENT,
        direction,
    )


def _flow(**overrides: object) -> OrderFlowSnapshot:
    values: dict[str, object] = {
        "instrument": "EUR_USD",
        "observed_at": NOW,
        "source": "cme_fx_futures",
        "directional_pressure": Decimal("0.6"),
        "vwap": Decimal("1.1000"),
        "confidence": Decimal("0.9"),
    }
    values.update(overrides)
    return OrderFlowSnapshot(**values)  # type: ignore[arg-type]


def test_technical_window_validation_fail_closed() -> None:
    with pytest.raises(ValueError, match="instrument"):
        TechnicalWindow(" ", "M5", _candles())
    with pytest.raises(ValueError, match="timeframe"):
        TechnicalWindow("EUR_USD", " ", _candles())
    with pytest.raises(ValueError, match="at least 8"):
        TechnicalWindow("EUR_USD", "M5", _candles(count=7))
    with pytest.raises(ValueError, match="chronologically"):
        TechnicalWindow("EUR_USD", "M5", tuple(reversed(_candles())))
    incomplete = list(_candles())
    incomplete[-1] = replace(incomplete[-1], complete=False)
    with pytest.raises(ValueError, match="completed candles"):
        TechnicalWindow("EUR_USD", "M5", tuple(incomplete))
    duplicated = list(_candles())
    duplicated[-1] = replace(duplicated[-1], time=duplicated[-2].time)
    with pytest.raises(ValueError, match="chronologically|unique"):
        TechnicalWindow("EUR_USD", "M5", tuple(duplicated))


def test_technical_batch_and_split_validation_fail_closed() -> None:
    batch = build_blinded_technical_batch([_window()], frozen_as_of=NOW)
    packet = batch.packets[0]
    with pytest.raises(ValueError, match="timezone-aware"):
        replace(packet, window_start=packet.window_start.replace(tzinfo=None))
    with pytest.raises(ValueError, match="precedes"):
        replace(packet, window_end=packet.window_start - timedelta(seconds=1))
    with pytest.raises(ValueError, match="timezone-aware"):
        TechnicalAnnotationBatch(batch.batch_id, batch.policy_version, NOW.replace(tzinfo=None), batch.packets)
    with pytest.raises(ValueError, match="must contain packets"):
        TechnicalAnnotationBatch("empty", batch.policy_version, NOW, ())
    with pytest.raises(ValueError, match="unique"):
        TechnicalAnnotationBatch("dup", batch.policy_version, NOW, (packet, packet))
    with pytest.raises(ValueError, match="timezone-aware"):
        build_blinded_technical_batch([_window()], frozen_as_of=NOW.replace(tzinfo=None))
    future_window = TechnicalWindow(
        "EUR_USD",
        "M5",
        tuple(replace(candle, time=candle.time + timedelta(days=2)) for candle in _candles()),
    )
    with pytest.raises(ValueError, match="after frozen_as_of"):
        build_blinded_technical_batch([future_window], frozen_as_of=NOW)
    with pytest.raises(ValueError, match="empty"):
        build_blinded_technical_batch([], frozen_as_of=NOW)
    with pytest.raises(ValueError, match="at least 3"):
        split_technical_calibration_holdout(batch)


def test_technical_finalization_rejects_identity_and_adjudication_failures() -> None:
    batch = build_blinded_technical_batch([_window()], frozen_as_of=NOW)
    packet_id = batch.packets[0].packet_id
    good = TechnicalReviewerSubmission(packet_id, "a", _label())
    second = TechnicalReviewerSubmission(packet_id, "b", _label())
    with pytest.raises(ValueError, match="at least two"):
        finalize_technical_labels(batch, [good, second], minimum_reviewers=1)
    with pytest.raises(ValueError, match="not in batch"):
        finalize_technical_labels(batch, [good, second], required_packet_ids=["unknown"])
    with pytest.raises(ValueError, match="unknown packet"):
        finalize_technical_labels(batch, [TechnicalReviewerSubmission("unknown", "a", _label())])
    with pytest.raises(ValueError, match="duplicate reviewer"):
        finalize_technical_labels(batch, [good, good])
    with pytest.raises(ValueError, match="unknown packet"):
        finalize_technical_labels(
            batch,
            [good, second],
            [TechnicalAdjudication("unknown", "c", _label())],
        )
    with pytest.raises(ValueError, match="duplicate adjudication"):
        finalize_technical_labels(
            batch,
            [good, second],
            [
                TechnicalAdjudication(packet_id, "c", _label()),
                TechnicalAdjudication(packet_id, "d", _label()),
            ],
        )
    with pytest.raises(ValueError, match="reviewers"):
        finalize_technical_labels(batch, [good])
    with pytest.raises(ValueError, match="independent"):
        finalize_technical_labels(
            batch,
            [good, second],
            [TechnicalAdjudication(packet_id, "a", _label())],
        )
    with pytest.raises(ValueError, match="contradicts"):
        finalize_technical_labels(
            batch,
            [good, second],
            [TechnicalAdjudication(packet_id, "c", _label(TechnicalDirectionLabel.SHORT))],
        )

    disagree = TechnicalReviewerSubmission(packet_id, "b", _label(TechnicalDirectionLabel.SHORT))
    with pytest.raises(ValueError, match="independent"):
        finalize_technical_labels(
            batch,
            [good, disagree],
            [TechnicalAdjudication(packet_id, "a", _label(TechnicalDirectionLabel.AMBIGUOUS))],
        )

    unanimous = finalize_technical_labels(
        batch,
        [good, second],
        [TechnicalAdjudication(packet_id, "c", _label())],
    )
    assert unanimous.labels[0].agreement
    assert label_payload(unanimous.labels[0].label)["direction"] == "long"


def test_technical_payload_validation_detects_tampering() -> None:
    batch = build_blinded_technical_batch([_window()], frozen_as_of=NOW)
    payload = batch.public_payload()
    restored = technical_batch_from_payload(payload)
    assert restored.batch_id == batch.batch_id

    bad_schema = dict(payload)
    bad_schema["schema_version"] = "9"
    with pytest.raises(ValueError, match="schema_version"):
        technical_batch_from_payload(bad_schema)

    bad_packets = dict(payload)
    bad_packets["packets"] = "not-a-list"
    with pytest.raises(ValueError, match="packets must be a list"):
        technical_batch_from_payload(bad_packets)

    raw_packets = payload["packets"]
    assert isinstance(raw_packets, list)
    with pytest.raises(ValueError, match="packet must be an object"):
        technical_batch_from_payload({**payload, "packets": ["bad"]})

    packet = dict(raw_packets[0])
    packet["candles"] = "bad"
    with pytest.raises(ValueError, match="candles must be a list"):
        technical_batch_from_payload({**payload, "packets": [packet]})

    packet = dict(raw_packets[0])
    candles = list(packet["candles"])
    first = dict(candles[0])
    first["close"] = "9.9999"
    candles[0] = first
    packet["candles"] = candles
    with pytest.raises(ValueError, match="hash mismatch"):
        technical_batch_from_payload({**payload, "packets": [packet]})

    packet = dict(raw_packets[0])
    packet["candles"] = ["bad", *list(packet["candles"])[1:]]
    with pytest.raises(ValueError, match="candle payload"):
        technical_batch_from_payload({**payload, "packets": [packet]})

    packet = dict(raw_packets[0])
    candles = list(packet["candles"])
    first = dict(candles[0])
    first["time"] = "2026-08-07T12:00:00"
    candles[0] = first
    packet["candles"] = candles
    with pytest.raises(ValueError, match="timezone-aware"):
        technical_batch_from_payload({**payload, "packets": [packet]})


def test_macro_factor_policy_validation_and_pricing_paths(tmp_path) -> None:  # type: ignore[no-untyped-def]
    with pytest.raises(ValueError, match="positive"):
        MacroFactorClusterGuard(default_macro_factor_map(), maximum_factor_exposure_fraction=Decimal("0"))
    with pytest.raises(ValueError, match="must not be empty"):
        MacroFactorClusterGuard({"EUR_USD": ()})
    with pytest.raises(ValueError, match="must not be empty"):
        MacroFactorClusterGuard({})

    path = tmp_path / "factor.json"
    path.write_text("[]")
    with pytest.raises(ValueError, match="JSON object"):
        MacroFactorClusterGuard.from_json_file(path)
    path.write_text(json.dumps({"maximum_factor_exposure_fraction": "2"}))
    with pytest.raises(ValueError, match="instrument_factors"):
        MacroFactorClusterGuard.from_json_file(path)
    path.write_text(json.dumps({"instrument_factors": {"EUR_USD": "usd_rates"}}))
    with pytest.raises(ValueError, match="string list"):
        MacroFactorClusterGuard.from_json_file(path)

    path.write_text(
        json.dumps(
            {
                "maximum_factor_exposure_fraction": "4",
                "require_classification": false,
                "instrument_factors": {"EUR_USD": ["usd_rates"]},
            }
        ).replace("false", "false")
    )
    loaded = MacroFactorClusterGuard.from_json_file(path)
    assert loaded.maximum_factor_exposure_fraction == Decimal("4")
    assert not loaded.require_classification

    with pytest.raises(ValueError, match="capital_base"):
        loaded.evaluate_candidate(
            candidate_instrument="EUR_USD",
            candidate_direction=Direction.LONG,
            candidate_units=1,
            candidate_entry_price=Decimal("1.1"),
            positions=(),
            account_currency="USD",
            capital_base=Decimal("0"),
            conversion_rate=lambda _a, _b: Decimal("1"),
            mark_price=lambda _i: Decimal("1"),
        )
    with pytest.raises(ValueError, match="candidate_units"):
        loaded.evaluate_candidate(
            candidate_instrument="EUR_USD",
            candidate_direction=Direction.LONG,
            candidate_units=0,
            candidate_entry_price=Decimal("1.1"),
            positions=(),
            account_currency="USD",
            capital_base=Decimal("100"),
            conversion_rate=lambda _a, _b: Decimal("1"),
            mark_price=lambda _i: Decimal("1"),
        )

    non_strict = MacroFactorClusterGuard(default_macro_factor_map(), require_classification=False)
    decision = non_strict.evaluate_candidate(
        candidate_instrument="XAU_USD",
        candidate_direction=Direction.SHORT,
        candidate_units=1,
        candidate_entry_price=Decimal("2000"),
        positions=(),
        account_currency="USD",
        capital_base=Decimal("100000"),
        conversion_rate=lambda _a, _b: Decimal("1"),
        mark_price=lambda _i: Decimal("2000"),
    )
    assert not decision.blocked
    assert decision.report.unclassified_instruments == ("XAU_USD",)

    priced = MacroFactorClusterGuard(default_macro_factor_map(), maximum_factor_exposure_fraction=Decimal("10"))
    existing = [OpenPosition("EUR_GBP", long_units=Decimal("100"), long_average_price=Decimal("0.85"))]
    unpriced_mark = priced.evaluate_candidate(
        candidate_instrument="EUR_USD",
        candidate_direction=Direction.LONG,
        candidate_units=1,
        candidate_entry_price=Decimal("1.1"),
        positions=existing,
        account_currency="USD",
        capital_base=Decimal("100000"),
        conversion_rate=lambda _a, _b: Decimal("1.25"),
        mark_price=lambda _i: None,
    )
    assert unpriced_mark.blocked
    assert "EUR_GBP" in unpriced_mark.report.unpriced_instruments

    unpriced_fx = priced.evaluate_candidate(
        candidate_instrument="EUR_USD",
        candidate_direction=Direction.LONG,
        candidate_units=1,
        candidate_entry_price=Decimal("1.1"),
        positions=existing,
        account_currency="USD",
        capital_base=Decimal("100000"),
        conversion_rate=lambda _a, _b: None,
        mark_price=lambda _i: Decimal("0.85"),
    )
    assert unpriced_fx.blocked


def test_research_flow_strategies_cover_ineligible_watching_and_short_paths() -> None:
    divergence = FlowDivergenceResearchPolicy()
    assert divergence.evaluate(
        None,
        price_change=Decimal("0"),
        pip_size=Decimal("0.0001"),
        at_key_location=False,
        structure_shift=False,
    ).state is ResearchFlowState.INELIGIBLE
    assert divergence.evaluate(
        _flow(directional_pressure=None),
        price_change=Decimal("0"),
        pip_size=Decimal("0.0001"),
        at_key_location=False,
        structure_shift=False,
    ).state is ResearchFlowState.INELIGIBLE
    assert divergence.evaluate(
        _flow(confidence=Decimal("0.2")),
        price_change=Decimal("0"),
        pip_size=Decimal("0.0001"),
        at_key_location=False,
        structure_shift=False,
    ).state is ResearchFlowState.INELIGIBLE
    with pytest.raises(ValueError, match="pip_size"):
        divergence.evaluate(
            _flow(),
            price_change=Decimal("0"),
            pip_size=Decimal("0"),
            at_key_location=False,
            structure_shift=False,
        )
    watching = divergence.evaluate(
        _flow(),
        price_change=Decimal("0.0001"),
        pip_size=Decimal("0.0001"),
        at_key_location=False,
        structure_shift=False,
    )
    assert watching.state is ResearchFlowState.WATCHING
    bearish = divergence.evaluate(
        _flow(directional_pressure=Decimal("-0.7")),
        price_change=Decimal("0.0004"),
        pip_size=Decimal("0.0001"),
        at_key_location=True,
        structure_shift=True,
    )
    assert bearish.state is ResearchFlowState.CONFIRMED
    assert bearish.direction is Direction.SHORT

    vwap = VwapRepositioningResearchPolicy()
    with pytest.raises(ValueError, match="pip_size"):
        vwap.evaluate(
            _flow(),
            previous_price=Decimal("1"),
            current_price=Decimal("1"),
            pip_size=Decimal("0"),
            structure_shift=False,
        )
    no_vwap = vwap.evaluate(
        _flow(vwap=None),
        previous_price=Decimal("1.099"),
        current_price=Decimal("1.101"),
        pip_size=Decimal("0.0001"),
        structure_shift=False,
    )
    assert no_vwap.state is ResearchFlowState.INELIGIBLE
    no_cross = vwap.evaluate(
        _flow(),
        previous_price=Decimal("1.1000"),
        current_price=Decimal("1.1001"),
        pip_size=Decimal("0.0001"),
        structure_shift=False,
    )
    assert no_cross.state is ResearchFlowState.WATCHING
    misaligned = vwap.evaluate(
        _flow(directional_pressure=Decimal("-0.6")),
        previous_price=Decimal("1.0990"),
        current_price=Decimal("1.1010"),
        pip_size=Decimal("0.0001"),
        structure_shift=True,
    )
    assert misaligned.state is ResearchFlowState.ARMED
    short = vwap.evaluate(
        _flow(directional_pressure=Decimal("-0.6")),
        previous_price=Decimal("1.1010"),
        current_price=Decimal("1.0990"),
        pip_size=Decimal("0.0001"),
        structure_shift=True,
    )
    assert short.state is ResearchFlowState.CONFIRMED
    assert short.direction is Direction.SHORT
