from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path

from forex_trader.research.replay_archive import EXECUTABLE_QUOTE_EVENT, ReplayArchiveBundle


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Validate an integrity-bound point-in-time multi-source replay archive."
    )
    parser.add_argument("manifest", type=Path)
    parser.add_argument("--output", type=Path, default=None, help="Optional JSON validation report")
    args = parser.parse_args()

    bundle = ReplayArchiveBundle.load(args.manifest)
    event_types = Counter(record.event_type for record in bundle.records)
    providers = Counter(record.provider for record in bundle.records)
    quote_instruments = Counter(
        str(record.payload.get("instrument", "")).upper()
        for record in bundle.records
        if record.event_type == EXECUTABLE_QUOTE_EVENT
    )
    report = {
        "schema_version": "1.0",
        "dataset_id": bundle.manifest.dataset_id,
        "manifest_hash": bundle.manifest.manifest_hash,
        "archive_hash": bundle.archive_hash,
        "period_start": bundle.manifest.period_start.isoformat(),
        "period_end": bundle.manifest.period_end.isoformat(),
        "records": len(bundle.records),
        "event_types": dict(sorted(event_types.items())),
        "providers": dict(sorted(providers.items())),
        "quote_instruments": dict(sorted((key, value) for key, value in quote_instruments.items() if key)),
        "required_event_types": list(bundle.manifest.required_event_types),
        "status": "valid",
    }
    serialized = json.dumps(report, indent=2, sort_keys=True) + "\n"
    if args.output is None:
        print(serialized, end="")
    else:
        args.output.write_text(serialized)


if __name__ == "__main__":
    main()
