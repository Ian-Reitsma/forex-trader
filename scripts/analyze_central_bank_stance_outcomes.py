"""Build point-in-time research-only FX outcomes for source-backed central-bank stance evidence."""
from __future__ import annotations

import argparse
import json
from dataclasses import asdict
from datetime import datetime
from decimal import Decimal, InvalidOperation
from enum import Enum
from pathlib import Path

from forex_trader.infrastructure.official_document_repository import OfficialDocumentRepository
from forex_trader.research.path_dataset import load_candle_archive
from forex_trader.research.stance_outcomes import (
    DEFAULT_STANCE_HORIZONS_MINUTES,
    StanceOutcomeDataset,
    build_stance_outcome_dataset,
)


def analyze_stance_outcomes(
    document_database: Path,
    candle_archive: Path,
    *,
    family_id: str,
    instrument: str,
    horizon_minutes: tuple[int, ...] = DEFAULT_STANCE_HORIZONS_MINUTES,
    max_baseline_delay_seconds: Decimal = Decimal("300"),
    as_of: datetime | None = None,
) -> StanceOutcomeDataset:
    requested_family = family_id.strip()
    if not requested_family:
        raise ValueError("family_id is required")
    normalized_instrument = instrument.strip().upper()
    if not normalized_instrument:
        raise ValueError("instrument is required")
    repository = OfficialDocumentRepository(document_database)
    versions = repository.family_versions(requested_family)
    if len(versions) < 2:
        raise ValueError(f"family {requested_family} requires at least two persisted document versions")
    candles_by_instrument = load_candle_archive(candle_archive)
    candles = candles_by_instrument.get(normalized_instrument)
    if candles is None:
        raise ValueError(f"candle archive contains no observations for {normalized_instrument}")
    return build_stance_outcome_dataset(
        versions,
        candles,
        instrument=normalized_instrument,
        horizon_minutes=horizon_minutes,
        max_baseline_delay_seconds=max_baseline_delay_seconds,
        as_of=as_of,
    )


def _parse_horizons(value: str) -> tuple[int, ...]:
    parts = tuple(part.strip() for part in value.split(",") if part.strip())
    if not parts:
        raise ValueError("horizon minutes are required")
    try:
        return tuple(int(part) for part in parts)
    except ValueError as exc:
        raise ValueError("horizon minutes must be comma-separated integers") from exc


def _parse_as_of(value: str | None) -> datetime | None:
    if value is None:
        return None
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None:
        raise ValueError("as_of must be timezone-aware")
    return parsed


def _parse_decimal(value: str, name: str) -> Decimal:
    try:
        parsed = Decimal(value)
    except InvalidOperation as exc:
        raise ValueError(f"{name} must be a decimal") from exc
    return parsed


def _json_safe(value: object) -> object:
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, dict):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        return [_json_safe(item) for item in value]
    return value


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("document_database", type=Path)
    parser.add_argument("candle_archive", type=Path)
    parser.add_argument("--family-id", required=True)
    parser.add_argument("--instrument", required=True)
    parser.add_argument(
        "--horizon-minutes",
        default=",".join(str(item) for item in DEFAULT_STANCE_HORIZONS_MINUTES),
        help="comma-separated complete outcome panel horizons, default: 5,15,60,240",
    )
    parser.add_argument("--max-baseline-delay-seconds", default="300")
    parser.add_argument("--as-of", default=None)
    parser.add_argument("--output", type=Path, default=None)
    args = parser.parse_args()

    try:
        dataset = analyze_stance_outcomes(
            args.document_database,
            args.candle_archive,
            family_id=args.family_id,
            instrument=args.instrument,
            horizon_minutes=_parse_horizons(args.horizon_minutes),
            max_baseline_delay_seconds=_parse_decimal(
                args.max_baseline_delay_seconds,
                "max_baseline_delay_seconds",
            ),
            as_of=_parse_as_of(args.as_of),
        )
    except (FileNotFoundError, ValueError) as exc:
        raise SystemExit(str(exc)) from exc
    payload = _json_safe(asdict(dataset))
    text = json.dumps(payload, indent=2, sort_keys=True)
    if args.output is not None:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(text + "\n", encoding="utf-8")
    print(text)


if __name__ == "__main__":
    main()
