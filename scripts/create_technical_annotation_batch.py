from __future__ import annotations

import argparse
import json
from datetime import datetime
from decimal import Decimal
from pathlib import Path

from forex_trader.domain.models import Candle
from forex_trader.research.technical_annotation import (
    TechnicalWindow,
    build_blinded_technical_batch,
    split_technical_calibration_holdout,
)

_ALLOWED_WINDOW_KEYS = {"instrument", "timeframe", "candles"}
_ALLOWED_CANDLE_KEYS = {"time", "open", "high", "low", "close", "volume", "complete"}


def _aware(value: object) -> datetime:
    if not isinstance(value, str):
        raise ValueError("timestamp must be an ISO-8601 string")
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("timestamp must be timezone-aware")
    return parsed


def _window(payload: object) -> TechnicalWindow:
    if not isinstance(payload, dict):
        raise ValueError("each technical window must be an object")
    unexpected = set(payload) - _ALLOWED_WINDOW_KEYS
    if unexpected:
        raise ValueError(
            "technical annotation input must contain raw chart data only; "
            f"unexpected fields: {', '.join(sorted(unexpected))}"
        )
    raw_candles = payload.get("candles")
    if not isinstance(raw_candles, list):
        raise ValueError("technical window candles must be a list")
    candles: list[Candle] = []
    for raw in raw_candles:
        if not isinstance(raw, dict):
            raise ValueError("candle must be an object")
        unexpected_candle = set(raw) - _ALLOWED_CANDLE_KEYS
        if unexpected_candle:
            raise ValueError(f"unexpected candle fields: {', '.join(sorted(unexpected_candle))}")
        candles.append(
            Candle(
                time=_aware(raw["time"]),
                open=Decimal(str(raw["open"])),
                high=Decimal(str(raw["high"])),
                low=Decimal(str(raw["low"])),
                close=Decimal(str(raw["close"])),
                volume=int(raw.get("volume", 0)),
                complete=bool(raw.get("complete", True)),
            )
        )
    return TechnicalWindow(str(payload["instrument"]), str(payload["timeframe"]), tuple(candles))


def _manifest_payload(manifest: object) -> dict[str, object]:
    return {
        "schema_version": "1.0",
        "batch_id": manifest.batch_id,  # type: ignore[attr-defined]
        "policy_version": manifest.policy_version,  # type: ignore[attr-defined]
        "frozen_as_of": manifest.frozen_as_of.isoformat(),  # type: ignore[attr-defined]
        "calibration_packet_ids": list(manifest.calibration_packet_ids),  # type: ignore[attr-defined]
        "holdout_packet_ids": list(manifest.holdout_packet_ids),  # type: ignore[attr-defined]
        "manifest_hash": manifest.manifest_hash,  # type: ignore[attr-defined]
    }


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Create a blinded raw-candle technical annotation batch and fixed chronological holdout."
    )
    parser.add_argument("input", type=Path, help="JSON array or {'windows': [...]} containing raw chart windows only")
    parser.add_argument("--as-of", required=True, help="Frozen timezone-aware ISO-8601 cutoff")
    parser.add_argument("--batch-output", type=Path, required=True)
    parser.add_argument("--manifest-output", type=Path, required=True)
    args = parser.parse_args()

    payload = json.loads(args.input.read_text())
    raw_windows = payload.get("windows") if isinstance(payload, dict) else payload
    if not isinstance(raw_windows, list):
        raise ValueError("technical annotation input must be a JSON list or {'windows': [...]} object")
    windows = tuple(_window(item) for item in raw_windows)
    batch = build_blinded_technical_batch(windows, frozen_as_of=_aware(args.as_of))
    manifest = split_technical_calibration_holdout(batch)
    args.batch_output.write_text(json.dumps(batch.public_payload(), indent=2, sort_keys=True) + "\n")
    args.manifest_output.write_text(json.dumps(_manifest_payload(manifest), indent=2, sort_keys=True) + "\n")


if __name__ == "__main__":
    main()
