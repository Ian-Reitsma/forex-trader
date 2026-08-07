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
