"""Run the preregistered candidate-outcome study without broker write authority.

The horizons are fixed in code before outcomes are inspected. OANDA Practice candles are
fetched once per instrument and reused across every horizon so comparisons share the same
market evidence. The study labels all trade candidates, including candidates later denied
by risk, and never submits/modifies/closes an order.
"""
from __future__ import annotations

import argparse
import json
from collections import defaultdict
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from statistics import mean

from forex_trader.adapters.oanda_safe import SafeOandaPracticeClient
from forex_trader.config import AppConfig
from forex_trader.domain.enums import ProviderKind
from forex_trader.research.dataset import append_outcome_evidence, decision_key, label_mature_decisions
from forex_trader.research.evidence import DecisionEvidence, load_decision_evidence

PREREGISTERED_HORIZONS = (6, 12, 24, 48, 72, 144, 288)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Label candidate outcomes at fixed M5 horizons: 6,12,24,48,72,144,288 bars.")
    parser.add_argument("decision_evidence", type=Path)
    parser.add_argument("--output-dir", type=Path, default=Path("diagnostics/candidate-horizon-study"))
    parser.add_argument("--entry-delay-bars", type=int, default=0)
    parser.add_argument("--entry-slippage-pips", type=Decimal, default=Decimal("0.10"))
    parser.add_argument("--exit-slippage-pips", type=Decimal, default=Decimal("0.10"))
    parser.add_argument("--maximum-pages", type=int, default=200)
    parser.add_argument("--overwrite", action="store_true")
    return parser


def _score_bucket(decision: DecisionEvidence) -> str:
    if decision.score is None:
        return "unknown"
    score = decision.score
    if score < Decimal("0.75"):
        return "<0.75"
    if score < Decimal("0.80"):
        return "0.75-0.80"
    if score < Decimal("0.85"):
        return "0.80-0.85"
    if score < Decimal("0.90"):
        return "0.85-0.90"
    return ">=0.90"


def _summarize(rows: list[object]) -> dict[str, object]:
    if not rows:
        return {"trades": 0}
    r_values = [Decimal(str(getattr(row, "r_multiple"))) for row in rows]
    mfe = [Decimal(str(getattr(row, "maximum_favorable_r"))) for row in rows]
    mae = [Decimal(str(getattr(row, "maximum_adverse_r"))) for row in rows]
    costs = [Decimal(str(getattr(row, "estimated_cost_r"))) for row in rows]
    statuses = [str(getattr(row, "status")) for row in rows]
    return {
        "trades": len(rows),
        "wins": statuses.count("win"),
        "losses": statuses.count("loss"),
        "timeouts": statuses.count("timeout"),
        "win_rate": str(Decimal(statuses.count("win")) / Decimal(len(rows))),
        "expectancy_r": str(sum(r_values, Decimal("0")) / Decimal(len(rows))),
        "total_r": str(sum(r_values, Decimal("0"))),
        "average_mfe_r": str(Decimal(str(mean(mfe)))),
        "average_mae_r": str(Decimal(str(mean(mae)))),
        "average_estimated_cost_r": str(Decimal(str(mean(costs)))),
    }


def _group_summary(outcomes: tuple[object, ...], decisions_by_key: dict[str, DecisionEvidence], field: str) -> dict[str, object]:
    groups: dict[str, list[object]] = defaultdict(list)
    for outcome in outcomes:
        decision = decisions_by_key.get(str(getattr(outcome, "decision_key")))
        if decision is None:
            continue
        if field == "score_bucket":
            key = _score_bucket(decision)
        else:
            raw = getattr(decision, field)
            key = str(raw) if raw not in {None, ""} else "unknown"
        groups[key].append(outcome)
    return {key: _summarize(rows) for key, rows in sorted(groups.items())}


def main() -> int:
    args = _parser().parse_args()
    if args.entry_delay_bars < 0:
        raise SystemExit("--entry-delay-bars cannot be negative")
    if args.entry_slippage_pips < 0 or args.exit_slippage_pips < 0:
        raise SystemExit("slippage assumptions cannot be negative")
    if args.maximum_pages < 1:
        raise SystemExit("--maximum-pages must be positive")

    config = AppConfig.from_env()
    errors = config.validate()
    if errors:
        raise SystemExit("invalid configuration: " + "; ".join(errors))
    if config.provider is not ProviderKind.OANDA or config.oanda_token is None:
        raise SystemExit("candidate horizon study requires the OANDA Practice market-data configuration")

    decisions = load_decision_evidence(args.decision_evidence)
    candidates = tuple(record for record in decisions if record.is_trade_candidate and record.signal_time is not None)
    if not candidates:
        raise SystemExit("decision evidence contains no trade candidates with signal times")
    policy_fingerprints = {record.policy_fingerprint for record in candidates}
    if len(policy_fingerprints) != 1:
        raise SystemExit("candidate horizon study requires one immutable policy fingerprint")

    now = datetime.now(UTC)
    by_instrument: dict[str, list[DecisionEvidence]] = defaultdict(list)
    for record in candidates:
        by_instrument[record.instrument].append(record)

    client = SafeOandaPracticeClient(
        token=config.oanda_token,
        account_id=config.oanda_account_id,
        rest_url=config.oanda_rest_url,
        stream_url=config.oanda_stream_url,
        timeout_seconds=config.oanda_timeout_seconds,
    )
    candles_by_instrument = {}
    for instrument, records in sorted(by_instrument.items()):
        starts = [record.signal_time for record in records if record.signal_time is not None]
        if not starts:
            continue
        candles_by_instrument[instrument] = client.candles_between(
            instrument,
            config.lower_timeframe,
            min(starts),
            now,
            maximum_pages=args.maximum_pages,
        )

    args.output_dir.mkdir(parents=True, exist_ok=True)
    expected_outputs = {bars: args.output_dir / f"outcomes-h{bars}.jsonl" for bars in PREREGISTERED_HORIZONS}
    existing = [str(path) for path in expected_outputs.values() if path.exists()]
    if existing and not args.overwrite:
        raise SystemExit("refusing to mix study runs with existing output; use a new directory or --overwrite: " + ", ".join(existing))
    if args.overwrite:
        for path in expected_outputs.values():
            path.unlink(missing_ok=True)

    decisions_by_key = {decision_key(record): record for record in candidates}
    horizon_reports: dict[str, object] = {}
    for bars in PREREGISTERED_HORIZONS:
        outcomes = label_mature_decisions(
            candidates,
            candles_by_instrument,
            maximum_bars=bars,
            spread_from_decision_quote=True,
            entry_slippage_pips=args.entry_slippage_pips,
            exit_slippage_pips=args.exit_slippage_pips,
            entry_delay_bars=args.entry_delay_bars,
            labeled_at=now,
            label_policy=(
                f"preregistered-horizon-v1:{config.lower_timeframe}:bars={bars}:"
                f"entry_delay={args.entry_delay_bars}:entry_slip={args.entry_slippage_pips}:"
                f"exit_slip={args.exit_slippage_pips}:decision_quote_spread=true"
            ),
        )
        output_path = expected_outputs[bars]
        for outcome in outcomes:
            append_outcome_evidence(output_path, outcome)
        horizon_reports[str(bars)] = {
            "minutes": bars * 5 if config.lower_timeframe == "M5" else None,
            "labeled": len(outcomes),
            "unmatured": len(candidates) - len(outcomes),
            "overall": _summarize(list(outcomes)),
            "by_risk_disposition": _group_summary(outcomes, decisions_by_key, "risk_disposition"),
            "by_instrument": _group_summary(outcomes, decisions_by_key, "instrument"),
            "by_regime": _group_summary(outcomes, decisions_by_key, "regime"),
            "by_session": _group_summary(outcomes, decisions_by_key, "session_phase"),
            "by_score_bucket": _group_summary(outcomes, decisions_by_key, "score_bucket"),
            "output": str(output_path),
        }

    manifest = {
        "schema": "preregistered-candidate-horizon-study-v1",
        "research_only": True,
        "broker_write_authority": False,
        "generated_at": now.isoformat(),
        "decision_evidence": str(args.decision_evidence),
        "policy_fingerprint": next(iter(policy_fingerprints)),
        "candidate_count": len(candidates),
        "horizons_bars": list(PREREGISTERED_HORIZONS),
        "horizon_selection": "fixed before outcome inspection; do not select a production horizon from this same sample",
        "assumptions": {
            "timeframe": config.lower_timeframe,
            "entry_delay_bars": args.entry_delay_bars,
            "entry_slippage_pips": str(args.entry_slippage_pips),
            "exit_slippage_pips": str(args.exit_slippage_pips),
            "spread": "captured decision quote",
            "same_bar_stop_target": "stop_first_conservative",
        },
        "horizons": horizon_reports,
    }
    manifest_path = args.output_dir / "manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({"manifest": str(manifest_path.resolve()), "candidate_count": len(candidates), "horizons": list(PREREGISTERED_HORIZONS)}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
