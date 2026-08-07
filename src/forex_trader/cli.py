from __future__ import annotations

import json
from pathlib import Path

import typer
import uvicorn

from forex_trader.api.app import create_app
from forex_trader.application.runner import run_cycles
from forex_trader.config import AppConfig, build_engine
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


@app.command(name="run")
def run_bot(
    interval_seconds: float = typer.Option(60.0, min=0.0),
    execute: bool = typer.Option(False, help="Allow paper orders when configuration also permits them"),
    max_cycles: int | None = typer.Option(None, min=1, help="Stop after this many cycles; omit to run continuously"),
    macro_file: Path | None = typer.Option(None, exists=True, dir_okay=False),
) -> None:
    """Run the polling bot until interrupted or max-cycles is reached."""
    config = AppConfig.from_env()
    engine = build_engine(config, macro_file=str(macro_file) if macro_file else None)
    traces = run_cycles(
        engine,
        config.instruments,
        execute=execute,
        interval_seconds=interval_seconds,
        max_cycles=max_cycles,
    )
    if max_cycles is not None:
        typer.echo(json.dumps([jsonable(trace) for trace in traces], indent=2))


@app.command()
def serve(
    host: str = typer.Option("127.0.0.1"),
    port: int = typer.Option(8000),
    macro_file: Path | None = typer.Option(None, exists=True, dir_okay=False),
) -> None:
    """Run the control API."""
    config = AppConfig.from_env()
    engine = build_engine(config, macro_file=str(macro_file) if macro_file else None)
    uvicorn.run(create_app(engine), host=host, port=port)
