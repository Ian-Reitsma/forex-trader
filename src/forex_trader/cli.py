from __future__ import annotations

import json
from pathlib import Path

import typer
import uvicorn

from forex_trader.api.app import create_app
from forex_trader.application.autonomous import AutonomousPracticeRuntime
from forex_trader.application.runner import run_cycles
from forex_trader.application.sync import BrokerStateSynchronizer
from forex_trader.config import AppConfig, build_engine
from forex_trader.domain.enums import OrderStatus, ProviderKind
from forex_trader.domain.models import jsonable

app = typer.Typer(no_args_is_help=True, help="Forex Trader paper-trading control CLI")


@app.command()
def doctor() -> None:
    """Validate configuration without connecting to a broker."""
    config = AppConfig.from_env()
    errors = config.validate()
    payload = {
        "provider": config.provider.value,
        "mode": config.mode.value,
        "instruments": config.instruments,
        "paper_orders_enabled": config.enable_paper_orders,
        "api_auth_configured": bool(config.api_token),
        "valid": not errors,
        "errors": errors,
    }
    typer.echo(json.dumps(payload, indent=2))
    if errors:
        raise typer.Exit(code=2)


@app.command()
def demo(
    instrument: str = typer.Option("EUR_USD", help="Instrument to evaluate"),
    execute: bool = typer.Option(False, help="Execute against the selected paper broker"),
    macro_file: Path | None = typer.Option(None, exists=True, dir_okay=False),
) -> None:
    """Run one deterministic evaluation using simulation by default."""
    config = AppConfig.from_env()
    engine = build_engine(config, macro_file=str(macro_file) if macro_file else None)
    trace = engine.evaluate(instrument, execute=execute)
    typer.echo(json.dumps(jsonable(trace), indent=2))


@app.command()
def cycle(
    execute: bool = typer.Option(False, help="Allow paper orders when configuration also permits them"),
    macro_file: Path | None = typer.Option(None, exists=True, dir_okay=False),
) -> None:
    """Evaluate every configured instrument once."""
    config = AppConfig.from_env()
    engine = build_engine(config, macro_file=str(macro_file) if macro_file else None)
    results = [jsonable(engine.evaluate(instrument, execute=execute)) for instrument in config.instruments]
    typer.echo(json.dumps(results, indent=2))


@app.command()
def scan(
    execute: bool = typer.Option(False, help="Permit eligible OANDA Practice orders when all other gates allow"),
    all_currency_pairs: bool = typer.Option(False, help="Discover the OANDA account's current currency instruments"),
    max_orders: int = typer.Option(1, min=0, help="Maximum Practice orders submitted during this scan"),
) -> None:
    """Scan configured or dynamically discovered FX pairs with a hard per-run order cap."""
    config = AppConfig.from_env()
    engine = build_engine(config)
    if all_currency_pairs:
        if config.provider is not ProviderKind.OANDA:
            raise typer.BadParameter("--all-currency-pairs requires FOREX_PROVIDER=oanda")
        instruments = engine.instrument_universe()
    else:
        instruments = config.instruments
    if not instruments:
        raise typer.BadParameter("the scan instrument universe is empty")
    results: list[dict[str, object]] = []
    submitted = 0
    for instrument in instruments:
        allow_write = execute and submitted < max_orders
        try:
            trace = engine.evaluate(instrument, execute=allow_write)
        except Exception as exc:
            results.append({"instrument": instrument, "error": f"{type(exc).__name__}: {str(exc)[:240]}"})
            continue
        if trace.order is not None and trace.order.status not in {OrderStatus.REJECTED, OrderStatus.CANCELLED}:
            submitted += 1
        results.append(
            {
                "instrument": instrument,
                "disposition": trace.candidate.disposition.value,
                "setup_state": trace.candidate.setup_state,
                "score": str(trace.candidate.score),
                "rejection_code": trace.candidate.rejection_code,
                "risk": trace.risk.disposition.value if trace.risk is not None else None,
                "order_status": trace.order.status.value if trace.order is not None else None,
            }
        )
    typer.echo(json.dumps({"instruments": len(instruments), "submitted_orders": submitted, "results": results}, indent=2))


@app.command(name="run")
def run_bot(
    interval_seconds: float | None = typer.Option(
        None, help="Polling interval; OANDA Practice execution defaults to the lower-timeframe bar"
    ),
    execute: bool = typer.Option(False, help="Allow paper orders when configuration also permits them"),
    max_cycles: int | None = typer.Option(None, min=1, help="Stop after this many cycles; omit to run continuously"),
    all_currency_pairs: bool = typer.Option(
        True,
        "--all-currency-pairs/--configured-pairs",
        help="OANDA Practice execution discovers and prefilters all broker currency pairs by default",
    ),
    max_orders_per_cycle: int = typer.Option(1, min=0),
    fundamental_refresh_seconds: float = typer.Option(3600.0, min=1.0),
    universe_refresh_seconds: float = typer.Option(3600.0, min=1.0),
    evidence_path: Path = typer.Option(Path("autonomous-campaign-evidence.jsonl")),
    decision_evidence_path: Path = typer.Option(Path("autonomous-decision-evidence.jsonl")),
    macro_file: Path | None = typer.Option(None, exists=True, dir_okay=False),
) -> None:
    """Run polling continuously; OANDA execute mode adds reconciliation and durable heartbeat."""
    config = AppConfig.from_env()
    if not execute and not all_currency_pairs:
        raise typer.BadParameter("--configured-pairs is only meaningful with OANDA --execute")

    if execute and config.provider is ProviderKind.OANDA:
        if macro_file is not None:
            raise typer.BadParameter("OANDA autonomous execution uses durable official fundamentals, not --macro-file")
        runtime = AutonomousPracticeRuntime(
            config,
            all_currency_pairs=all_currency_pairs,
            max_new_orders_per_cycle=max_orders_per_cycle,
            interval_seconds=interval_seconds,
            fundamental_refresh_seconds=fundamental_refresh_seconds,
            universe_refresh_seconds=universe_refresh_seconds,
            evidence_path=evidence_path,
            decision_evidence_path=decision_evidence_path,
        )
        runtime.run(
            max_cycles=max_cycles,
            on_cycle=lambda report: typer.echo(json.dumps(report.to_jsonable(), indent=2, sort_keys=True)),
        )
        return

    engine = build_engine(config, macro_file=str(macro_file) if macro_file else None)

    def report_error(instrument: str, exc: Exception) -> None:
        typer.echo(json.dumps({"instrument": instrument, "error": f"{type(exc).__name__}: {str(exc)[:240]}"}), err=True)

    traces = run_cycles(
        engine,
        config.instruments,
        execute=execute,
        interval_seconds=60.0 if interval_seconds is None else interval_seconds,
        max_cycles=max_cycles,
        on_error=report_error,
    )
    if max_cycles is not None:
        typer.echo(json.dumps([jsonable(trace) for trace in traces], indent=2))


@app.command()
def autonomous(
    interval_seconds: float | None = typer.Option(
        None, help="Defaults to one configured lower-timeframe bar"
    ),
    max_cycles: int | None = typer.Option(None, min=1, help="Omit to run continuously"),
    max_orders_per_cycle: int = typer.Option(1, min=0),
    fundamental_refresh_seconds: float = typer.Option(3600.0, min=1.0),
    universe_refresh_seconds: float = typer.Option(3600.0, min=1.0),
    evidence_path: Path = typer.Option(Path("autonomous-campaign-evidence.jsonl")),
    decision_evidence_path: Path = typer.Option(Path("autonomous-decision-evidence.jsonl")),
) -> None:
    """Run the canonical all-eligible-pair OANDA Practice daemon."""
    config = AppConfig.from_env()
    runtime = AutonomousPracticeRuntime(
        config,
        all_currency_pairs=True,
        max_new_orders_per_cycle=max_orders_per_cycle,
        interval_seconds=interval_seconds,
        fundamental_refresh_seconds=fundamental_refresh_seconds,
        universe_refresh_seconds=universe_refresh_seconds,
        evidence_path=evidence_path,
        decision_evidence_path=decision_evidence_path,
    )
    runtime.run(
        max_cycles=max_cycles,
        on_cycle=lambda report: typer.echo(json.dumps(report.to_jsonable(), indent=2, sort_keys=True)),
    )


@app.command()
def sync(
    stream: bool = typer.Option(False, help="Consume the OANDA transaction stream after REST catch-up"),
    max_events: int | None = typer.Option(None, min=1, help="Stop streaming after this many payloads"),
) -> None:
    """Backfill, catch up and optionally stream OANDA Practice transactions into SQLite."""
    config = AppConfig.from_env()
    if config.provider is not ProviderKind.OANDA:
        raise typer.BadParameter("FOREX_PROVIDER must be oanda for broker synchronization")
    engine = build_engine(config)
    synchronizer = BrokerStateSynchronizer(engine.broker, engine.repository)
    inserted = synchronizer.stream(max_events=max_events) if stream else synchronizer.catch_up()
    cursor = engine.repository.get_broker_cursor("oanda.transactions")
    typer.echo(json.dumps({"inserted": inserted, "cursor": cursor, "stream": stream}, indent=2))


@app.command()
def clear_halt(name: str = typer.Argument(..., help="Halt key, e.g. execution:<account-id>")) -> None:
    """Explicitly clear a persistent halt after broker/account reconciliation."""
    config = AppConfig.from_env()
    engine = build_engine(config)
    engine.clear_halt(name)
    typer.echo(json.dumps({"status": "cleared", "name": name}, indent=2))


@app.command()
def promotion() -> None:
    """Show whether accumulated practice evidence meets promotion gates."""
    config = AppConfig.from_env()
    engine = build_engine(config)
    typer.echo(json.dumps(engine.promotion_status(), indent=2))


@app.command()
def serve(
    host: str = typer.Option("127.0.0.1"),
    port: int = typer.Option(8000),
    macro_file: Path | None = typer.Option(None, exists=True, dir_okay=False),
) -> None:
    """Run the authenticated control API; external binds require FOREX_API_TOKEN."""
    config = AppConfig.from_env()
    loopback = host in {"127.0.0.1", "localhost", "::1"}
    if not loopback and not config.api_token:
        raise typer.BadParameter("FOREX_API_TOKEN is required when binding the control API beyond loopback")
    engine = build_engine(config, macro_file=str(macro_file) if macro_file else None)
    uvicorn.run(
        create_app(
            engine,
            api_token=config.api_token,
            allow_unsafe_local_mutations=loopback and not config.api_token,
        ),
        host=host,
        port=port,
    )