"""Validate central-bank stance market outcomes with a frozen chronological family-wise policy."""
from __future__ import annotations

import argparse
import json
from dataclasses import asdict
from datetime import datetime
from decimal import Decimal
from enum import Enum
from pathlib import Path

from forex_trader.infrastructure.official_document_repository import OfficialDocumentRepository
from forex_trader.research.path_dataset import load_candle_archive
from forex_trader.research.stance_outcomes import (
    DEFAULT_STANCE_HORIZONS_MINUTES,
    build_stance_outcome_dataset,
)
from forex_trader.research.stance_statistical_validation import (
    StanceStatisticalValidationReport,
    validate_stance_outcome_statistics,
)


FIXED_MAX_BASELINE_DELAY_SECONDS = Decimal("300")


def validate_stance_statistics_from_files(
    document_database: Path,
    candle_archive: Path,
    *,
    family_id: str,
    instrument: str,
    as_of: datetime,
) -> StanceStatisticalValidationReport:
    if as_of.tzinfo is None:
        raise ValueError("statistical validation as_of must be timezone-aware")
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
    dataset = build_stance_outcome_dataset(
        versions,
        candles,
        instrument=normalized_instrument,
        horizon_minutes=DEFAULT_STANCE_HORIZONS_MINUTES,
        max_baseline_delay_seconds=FIXED_MAX_BASELINE_DELAY_SECONDS,
        as_of=as_of,
    )
    if dataset.as_of != as_of:
        raise ValueError("statistical source dataset did not preserve the frozen as_of cutoff")
    if dataset.max_baseline_delay_seconds != FIXED_MAX_BASELINE_DELAY_SECONDS:
        raise ValueError("statistical source dataset did not preserve the fixed baseline-delay policy")
    return validate_stance_outcome_statistics(dataset)


def _parse_as_of(value: str) -> datetime:
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None:
        raise ValueError("as_of must be timezone-aware")
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
        "--as-of",
        required=True,
        help="timezone-aware frozen research cutoff; required to prevent an implicit moving sample",
    )
    parser.add_argument("--output", type=Path, default=None)
    args = parser.parse_args()
    try:
        report = validate_stance_statistics_from_files(
            args.document_database,
            args.candle_archive,
            family_id=args.family_id,
            instrument=args.instrument,
            as_of=_parse_as_of(args.as_of),
        )
    except (FileNotFoundError, ValueError) as exc:
        raise SystemExit(str(exc)) from exc
    text = json.dumps(_json_safe(asdict(report)), indent=2, sort_keys=True)
    if args.output is not None:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(text + "\n", encoding="utf-8")
    print(text)


if __name__ == "__main__":
    main()
