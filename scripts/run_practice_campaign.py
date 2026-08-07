"""Run an evidence-first FX shadow/Practice campaign.

The script never changes strategy thresholds. It can discover OANDA's real currency-pair
universe, caps new submissions per cycle, keeps evaluating remaining instruments in shadow
after the order budget is spent, and writes one cohort-fingerprinted JSONL evidence record
per cycle.

Before an authenticated campaign, run `forex-trader sync` and the read-only Practice probe.
Never put OANDA credentials on the command line; provide them through the local environment.
"""
from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path

from forex_trader.application.campaign import PracticeCampaignRunner
from forex_trader.application.campaign_policy import campaign_policy_context, select_campaign_universe
from forex_trader.config import AppConfig, build_engine
from forex_trader.domain.enums import OperatingMode, ProviderKind
from forex_trader.domain.timeframes import granularity_duration


def _exclusion_category(reason: str) -> str:
    lowered = reason.lower()
    if "missing fundamental state" in lowered:
        return "missing_fundamental_state"
    if "below" in lowered and "confidence" in lowered:
        return "low_fundamental_confidence"
    if "preflight failed" in lowered:
        return "fundamental_preflight_error"
    return "other_fundamental_exclusion"


parser = argparse.ArgumentParser()
parser.add_argument("--execute", action="store_true", help="Allow gated Practice submissions")
parser.add_argument(
    "--all-currency-pairs",
    action="store_true",
    help="Use the broker-discovered currency universe instead of FOREX_INSTRUMENTS",
)
parser.add_argument(
    "--eligible-only",
    action="store_true",
    help=(
        "In shadow mode, pre-filter pairs that cannot meet the configured fundamental-confidence gate. "
        "Execution campaigns apply this automatically when fundamentals are required."
    ),
)
parser.add_argument("--max-instruments", type=int, default=None)
parser.add_argument("--max-orders-per-cycle", type=int, default=1)
parser.add_argument("--max-cycles", type=int, default=1)
parser.add_argument(
    "--interval-seconds",
    type=float,
    default=None,
    help="Defaults to one configured lower-timeframe bar",
)
parser.add_argument(
    "--evidence-path",
    type=Path,
    default=Path("campaign-evidence.jsonl"),
)
args = parser.parse_args()

config = AppConfig.from_env()
errors = config.validate()
if errors:
    raise SystemExit("invalid configuration: " + "; ".join(errors))
if args.max_instruments is not None and args.max_instruments < 1:
    raise SystemExit("--max-instruments must be positive")
if args.max_orders_per_cycle < 0:
    raise SystemExit("--max-orders-per-cycle cannot be negative")
if args.max_cycles < 1:
    raise SystemExit("--max-cycles must be positive")
if args.execute:
    if config.provider is not ProviderKind.OANDA:
        raise SystemExit("--execute campaign is reserved for the OANDA Practice provider")
    if config.mode is not OperatingMode.PAPER or not config.enable_paper_orders:
        raise SystemExit(
            "--execute requires FOREX_MODE=paper and FOREX_ENABLE_PAPER_ORDERS=true"
        )

engine = build_engine(config)
if args.all_currency_pairs:
    discovered = tuple(engine.instrument_universe())
    universe_source = "broker"
else:
    discovered = tuple(config.instruments)
    universe_source = "configured"
if not discovered:
    raise SystemExit("campaign instrument universe is empty")

fundamental_preflight = bool(config.require_fundamentals and (args.execute or args.eligible_only))
selection = select_campaign_universe(
    engine,
    list(discovered),
    require_fundamental_coverage=fundamental_preflight,
)
eligible = selection.selected
if not eligible:
    if fundamental_preflight:
        raise SystemExit(
            "campaign has no instruments that can meet the current fundamental-confidence gate. "
            "Populate legitimate point-in-time fundamental data or run a shadow diagnostic without --eligible-only; "
            "do not lower strategy/risk gates merely to manufacture trades."
        )
    raise SystemExit("campaign instrument universe is empty after normalization")

instruments = eligible[: args.max_instruments] if args.max_instruments is not None else eligible
if not instruments:
    raise SystemExit("campaign instrument universe is empty after --max-instruments")

interval = (
    args.interval_seconds
    if args.interval_seconds is not None
    else granularity_duration(config.lower_timeframe).total_seconds()
)
if interval < 0:
    raise SystemExit("--interval-seconds cannot be negative")

exclusion_categories = Counter(_exclusion_category(reason) for reason in selection.excluded.values())
policy_context = campaign_policy_context(engine)
policy_context["campaign"] = {
    "execute": bool(args.execute),
    "max_new_orders_per_cycle": args.max_orders_per_cycle,
    "fundamental_preflight": fundamental_preflight,
}
campaign_metadata = {
    "universe_source": universe_source,
    "discovered_count": len(selection.discovered),
    "eligible_count": len(eligible),
    "run_count": len(instruments),
    "excluded_count": selection.excluded_count,
    "fundamental_preflight": fundamental_preflight,
    "excluded_reason_categories": dict(exclusion_categories),
}

runner = PracticeCampaignRunner(
    engine,
    instruments,
    execute=args.execute,
    max_new_orders_per_cycle=args.max_orders_per_cycle,
    stop_on_unresolved=True,
    evidence_path=args.evidence_path,
    policy_context=policy_context,
    campaign_metadata=campaign_metadata,
)


def emit(report):  # type: ignore[no-untyped-def]
    print(json.dumps(report.to_jsonable(), indent=2, sort_keys=True))


result = runner.run(
    max_cycles=args.max_cycles,
    interval_seconds=interval,
    on_cycle=emit,
)
print(
    json.dumps(
        {
            "campaign_complete": True,
            "campaign_id": runner.campaign_id,
            "policy_fingerprint": runner.policy_fingerprint,
            "mode": "practice-execution" if args.execute else "shadow",
            "provider": config.provider.value,
            "timeframe_policy": {
                "lower": config.lower_timeframe,
                "higher": config.higher_timeframe,
            },
            "universe": campaign_metadata,
            "cycles": len(result.cycles),
            "evaluations": result.evaluated,
            "orders_submitted": result.submitted,
            "unknown_orders": result.unknown,
            "unresolved_orders": result.unresolved,
            "evidence_path": str(args.evidence_path),
            "note": (
                "Trade frequency is an observed outcome. The campaign does not lower strategy/risk gates "
                "to manufacture fills. Any unresolved broker state stops further campaign risk."
            ),
        },
        indent=2,
        sort_keys=True,
    )
)
