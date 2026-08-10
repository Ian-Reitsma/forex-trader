"""Run an evidence-first FX shadow/Practice campaign.

The script never changes strategy thresholds. It can discover OANDA's real currency-pair
universe, caps new submissions per cycle, keeps evaluating remaining instruments in shadow
after the order budget is spent, writes cohort-fingerprinted cycle aggregates, can write
one point-in-time decision evidence row per instrument evaluation, and can capture six
paired research ablations from each exact shadow decision snapshot.

Before an authenticated campaign, run `forex-trader sync` and the read-only Practice probe.
Never put OANDA or licensed-data credentials on the command line; provide them through the
local environment. When TRADING_ECONOMICS_API_KEY is configured, Practice execution refreshes
prospective licensed macro observations before the fundamental-eligibility preflight.
"""
from __future__ import annotations

import argparse
import json
from collections import Counter
from hmac import compare_digest
from pathlib import Path

from forex_trader.application.campaign import PracticeCampaignRunner
from forex_trader.application.campaign_policy import campaign_policy_context, select_campaign_universe
from forex_trader.application.trading_economics_sync import sync_trading_economics_fundamentals
from forex_trader.config import AppConfig, build_engine
from forex_trader.domain.enums import OperatingMode, ProviderKind
from forex_trader.domain.timeframes import granularity_duration
from forex_trader.ingestion.trading_economics import TradingEconomicsSettings


def _exclusion_category(reason: str) -> str:
    lowered = reason.lower()
    if "missing fundamental state" in lowered:
        return "missing_fundamental_state"
    if "below" in lowered and "confidence" in lowered:
        return "low_fundamental_confidence"
    if "preflight failed" in lowered:
        return "fundamental_preflight_error"
    return "other_fundamental_exclusion"


def _validate_te_secret_separation(config: AppConfig, settings: TradingEconomicsSettings) -> None:
    if settings.api_key is None:
        return
    if config.api_token is not None and compare_digest(settings.api_key, config.api_token):
        raise SystemExit(
            "TRADING_ECONOMICS_API_KEY is cross-wired to FOREX_API_TOKEN. "
            "Use a credential issued by Trading Economics; the forex-trader control-plane token cannot authenticate Trading Economics."
        )
    if config.oanda_token is not None and compare_digest(settings.api_key, config.oanda_token):
        raise SystemExit(
            "TRADING_ECONOMICS_API_KEY is cross-wired to OANDA_API_TOKEN. "
            "Use a credential issued by Trading Economics; the OANDA Practice token cannot authenticate Trading Economics."
        )


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
    help="Cycle-level aggregate JSONL evidence",
)
parser.add_argument(
    "--decision-evidence-path",
    type=Path,
    default=None,
    help="Optional per-instrument point-in-time decision JSONL evidence",
)
parser.add_argument(
    "--ablation-evidence-path",
    type=Path,
    default=None,
    help=(
        "Optional shadow-only paired ablation JSONL. Emits full/no-fundamentals/no-flow/"
        "no-session/no-zone-quality/no-retest rows from one frozen production signal snapshot."
    ),
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
if args.execute and args.ablation_evidence_path is not None:
    raise SystemExit("--ablation-evidence-path is shadow-only and cannot be combined with --execute")
if args.execute:
    if config.provider is not ProviderKind.OANDA:
        raise SystemExit("--execute campaign is reserved for the OANDA Practice provider")
    if config.mode is not OperatingMode.PAPER or not config.enable_paper_orders:
        raise SystemExit(
            "--execute requires FOREX_MODE=paper and FOREX_ENABLE_PAPER_ORDERS=true"
        )

fundamental_refresh: dict[str, object] | None = None
te_settings = TradingEconomicsSettings.from_env()
_validate_te_secret_separation(config, te_settings)
if (
    args.execute
    and config.require_fundamentals
    and te_settings.auto_refresh
    and te_settings.api_key is not None
):
    try:
        refresh_report = sync_trading_economics_fundamentals(config.database_path, te_settings)
    except Exception as exc:
        raise SystemExit(
            f"Trading Economics fundamental refresh failed closed: {type(exc).__name__}: {exc}"
        ) from exc
    fundamental_refresh = refresh_report.to_jsonable()
    print(json.dumps({"fundamental_refresh": fundamental_refresh}, indent=2, sort_keys=True))

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
        provider_hint = (
            " Configure TRADING_ECONOMICS_API_KEY to enable the prospective licensed macro refresh."
            if te_settings.api_key is None
            else " The configured Trading Economics refresh completed but did not produce enough fresh confidence."
        )
        raise SystemExit(
            "campaign has no instruments that can meet the current fundamental-confidence gate. "
            "Populate legitimate point-in-time fundamental data or run a shadow diagnostic without --eligible-only; "
            "do not lower strategy/risk gates merely to manufacture trades."
            + provider_hint
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
    "paired_ablation_capture": args.ablation_evidence_path is not None,
    "licensed_fundamental_refresh": fundamental_refresh,
}
campaign_metadata = {
    "universe_source": universe_source,
    "discovered_count": len(selection.discovered),
    "eligible_count": len(eligible),
    "run_count": len(instruments),
    "excluded_count": selection.excluded_count,
    "fundamental_preflight": fundamental_preflight,
    "paired_ablation_capture": args.ablation_evidence_path is not None,
    "licensed_fundamental_refresh": fundamental_refresh,
    "excluded_reason_categories": dict(exclusion_categories),
}

runner = PracticeCampaignRunner(
    engine,
    instruments,
    execute=args.execute,
    max_new_orders_per_cycle=args.max_orders_per_cycle,
    stop_on_unresolved=True,
    evidence_path=args.evidence_path,
    decision_evidence_path=args.decision_evidence_path,
    ablation_evidence_path=args.ablation_evidence_path,
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
            "ablation_snapshots": result.ablation_snapshots,
            "ablation_rows": result.ablation_rows,
            "ablation_errors": result.ablation_errors,
            "evidence_path": str(args.evidence_path),
            "decision_evidence_path": str(args.decision_evidence_path) if args.decision_evidence_path else None,
            "ablation_evidence_path": str(args.ablation_evidence_path) if args.ablation_evidence_path else None,
            "note": (
                "Trade frequency is an observed outcome. The campaign does not lower strategy/risk gates "
                "to manufacture fills. Paired ablations are shadow-only and cannot authorize broker writes. "
                "Any unresolved broker state stops further campaign risk."
            ),
        },
        indent=2,
        sort_keys=True,
    )
)
