from typer.testing import CliRunner

from forex_trader.cli import app


def test_doctor_default_configuration(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.delenv("FOREX_PROVIDER", raising=False)
    monkeypatch.delenv("FOREX_MODE", raising=False)
    result = CliRunner().invoke(app, ["doctor"])
    assert result.exit_code == 0
    assert '"valid": true' in result.stdout


def test_demo_and_finite_run_commands(monkeypatch, tmp_path) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.setenv("FOREX_DATABASE_PATH", str(tmp_path / "cli.db"))
    runner = CliRunner()
    demo = runner.invoke(app, ["demo", "--instrument", "EUR_USD"])
    assert demo.exit_code == 0
    assert '"instrument": "EUR_USD"' in demo.stdout
    run = runner.invoke(app, ["run", "--max-cycles", "1", "--interval-seconds", "0"])
    assert run.exit_code == 0
    assert '"trace_id"' in run.stdout
