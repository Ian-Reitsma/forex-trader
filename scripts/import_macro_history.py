"""Import immutable point-in-time macro/news observations from JSON Lines.

Each line must contain `kind`, `currency`, and an ISO-8601 `available_at`. Release rows
also require category/actual/forecast/previous. When no observation ID is supplied, a
stable UUID is derived from the normalized row so re-importing the same history is
idempotent instead of silently duplicating evidence.
"""
from __future__ import annotations

import argparse
import json
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from uuid import NAMESPACE_URL, UUID, uuid5

from forex_trader.config import AppConfig
from forex_trader.domain.macro_history import MacroObservation, MacroObservationKind
from forex_trader.infrastructure.trading_repository import TradingRepository

parser = argparse.ArgumentParser()
parser.add_argument("path", type=Path)
args = parser.parse_args()
if not args.path.is_file():
    raise SystemExit(f"not a file: {args.path}")
repo = TradingRepository(AppConfig.from_env().database_path)
count = 0
for line_number, raw in enumerate(args.path.read_text().splitlines(), start=1):
    if not raw.strip() or raw.lstrip().startswith("#"):
        continue
    try:
        item = json.loads(raw)
        kind = MacroObservationKind(item["kind"])
        available_at = datetime.fromisoformat(item["available_at"].replace("Z", "+00:00"))
        if available_at.tzinfo is None:
            raise ValueError("available_at must be timezone-aware")
        canonical = json.dumps(item, sort_keys=True, separators=(",", ":"))
        observation_id = UUID(item["observation_id"]) if item.get("observation_id") else uuid5(NAMESPACE_URL, f"forex-trader:macro:{canonical}")
        revision_of = UUID(item["revision_of"]) if item.get("revision_of") else None
        observation = MacroObservation(
            observation_id=observation_id,
            kind=kind,
            currency=item["currency"].upper(),
            available_at=available_at,
            source=item.get("source", "import"),
            category=item.get("category", ""),
            actual=Decimal(str(item["actual"])) if item.get("actual") is not None else None,
            forecast=Decimal(str(item["forecast"])) if item.get("forecast") is not None else None,
            previous=Decimal(str(item["previous"])) if item.get("previous") is not None else None,
            higher_is_positive=bool(item.get("higher_is_positive", True)),
            importance=Decimal(str(item.get("importance", "1"))),
            headline=item.get("headline", ""),
            body=item.get("body", ""),
            source_weight=Decimal(str(item.get("source_weight", "0.7"))),
            revision_of=revision_of,
        )
    except Exception as exc:
        raise SystemExit(f"invalid line {line_number}: {exc}") from exc
    repo.save_macro_observation(observation)
    count += 1
print(json.dumps({"imported_or_already_present": count, "database": str(repo.path)}, indent=2))
