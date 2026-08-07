from forex_trader.config import AppConfig, load_macro_file
from forex_trader.domain.enums import OperatingMode, ProviderKind


def test_paper_oanda_requires_token() -> None:
    config = AppConfig(provider=ProviderKind.OANDA, mode=OperatingMode.PAPER)
    assert "OANDA_API_TOKEN" in config.validate()[0]


def test_default_macro_file_has_required_currencies() -> None:
    book = load_macro_file(None)
    assert book.get("EUR") is not None
    assert book.get("USD") is not None


def test_build_simulation_engine(tmp_path) -> None:
    from forex_trader.config import build_engine

    config = AppConfig(database_path=str(tmp_path / "test.db"))
    engine = build_engine(config)
    assert engine.status()["mode"] == "shadow"


def test_config_redacts_token_and_locks_practice_host() -> None:
    config = AppConfig(
        provider=ProviderKind.OANDA,
        mode=OperatingMode.PAPER,
        oanda_token="private-token",
        oanda_rest_url="https://api-fxtrade.oanda.com",
    )
    assert "private-token" not in repr(config)
    assert "locked" in "; ".join(config.validate())


def test_config_rejects_order_gate_outside_paper() -> None:
    config = AppConfig(enable_paper_orders=True, mode=OperatingMode.SHADOW)
    assert "paper orders" in "; ".join(config.validate())


def test_load_dotenv_does_not_override_existing_environment(monkeypatch, tmp_path) -> None:  # type: ignore[no-untyped-def]
    from forex_trader.config import load_dotenv

    env_file = tmp_path / ".env"
    env_file.write_text("# comment\nFOREX_PROVIDER=oanda\nIGNORED\n")
    monkeypatch.setenv("FOREX_PROVIDER", "simulation")
    load_dotenv(env_file)
    assert AppConfig.from_env().provider is ProviderKind.SIMULATION


def test_oanda_without_macro_file_starts_with_zero_confidence_priors(tmp_path) -> None:
    from forex_trader.config import build_engine

    config = AppConfig(
        provider=ProviderKind.OANDA,
        mode=OperatingMode.SHADOW,
        database_path=str(tmp_path / "oanda.db"),
        oanda_token="token",
    )
    engine = build_engine(config)
    assert engine.fundamentals.get("EUR") is not None
    assert engine.fundamentals.get("EUR").confidence == 0  # type: ignore[union-attr]


def test_config_locks_stream_host_and_exposure_limits() -> None:
    config = AppConfig(
        provider=ProviderKind.OANDA,
        oanda_token="token",
        oanda_stream_url="https://stream-fxtrade.oanda.com",
        max_currency_exposure_fraction=__import__("decimal").Decimal("0"),
    )
    errors = "; ".join(config.validate())
    assert "stream" in errors
    assert "exposure" in errors


def test_build_engine_replays_persisted_macro_history(tmp_path) -> None:
    from datetime import UTC, datetime
    from decimal import Decimal
    from forex_trader.config import build_engine
    from forex_trader.domain.macro_history import MacroObservation
    from forex_trader.infrastructure.repository import SqliteDecisionRepository

    db = tmp_path / "persist.db"
    repository = SqliteDecisionRepository(db)
    repository.save_macro_observation(
        MacroObservation.news(
            currency="EUR",
            headline="growth strong",
            source_weight=Decimal("1"),
            available_at=datetime.now(UTC),
        )
    )
    repository.close()
    engine = build_engine(AppConfig(database_path=str(db)))
    assert engine.fundamentals.get("EUR").news > 0  # type: ignore[union-attr]
