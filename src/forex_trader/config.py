from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from urllib.parse import urlparse

from forex_trader.adapters.oanda_safe import SafeOandaPracticeClient
from forex_trader.adapters.simulator import SimulatedPaperBroker
from forex_trader.adapters.synthetic import SyntheticMarketData
from forex_trader.application.engine import TradingEngine
from forex_trader.domain.costs import SessionCostModel
from forex_trader.domain.enums import OperatingMode, ProviderKind
from forex_trader.domain.fundamentals import FundamentalBook
from forex_trader.domain.macro_history import PointInTimeFundamentalBook
from forex_trader.domain.models import CurrencyFundamentals
from forex_trader.domain.risk import RiskPolicy
from forex_trader.domain.strategy import SignalFusionPolicy
from forex_trader.infrastructure.trading_repository import TradingRepository


def _bool(value: str | None, default: bool = False) -> bool:
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _decimal_env(name: str, default: str) -> Decimal:
    try:
        return Decimal(os.getenv(name, default))
    except Exception as exc:
        raise ValueError(f"{name} must be a decimal number") from exc


def load_dotenv(path: str | Path = ".env") -> None:
    file_path = Path(path)
    if not file_path.exists():
        return
    for raw_line in file_path.read_text().splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


@dataclass(frozen=True, slots=True)
class AppConfig:
    provider: ProviderKind = ProviderKind.SIMULATION
    mode: OperatingMode = OperatingMode.SHADOW
    database_path: str = "./forex_trader.db"
    instruments: tuple[str, ...] = ("EUR_USD",)
    require_fundamentals: bool = True
    enable_paper_orders: bool = False
    minimum_score: Decimal = Decimal("0.66")
    maximum_spread_pips: Decimal = Decimal("2.0")
    maximum_slippage_pips: Decimal = Decimal("0.5")
    risk_fraction: Decimal = Decimal("0.0015")
    max_daily_loss_fraction: Decimal = Decimal("0.01")
    max_open_positions: int = 3
    max_units: int = 100_000
    max_gross_exposure_fraction: Decimal = Decimal("4")
    max_currency_exposure_fraction: Decimal = Decimal("2")
    auto_discover_currency_instruments: bool = False
    api_token: str | None = field(default=None, repr=False)
    oanda_token: str | None = field(default=None, repr=False)
    oanda_account_id: str | None = None
    oanda_rest_url: str = "https://api-fxpractice.oanda.com"
    oanda_stream_url: str = "https://stream-fxpractice.oanda.com"
    oanda_timeout_seconds: float = 10.0

    @classmethod
    def from_env(cls) -> "AppConfig":
        load_dotenv()
        instruments = tuple(
            item.strip().upper()
            for item in os.getenv("FOREX_INSTRUMENTS", "EUR_USD").split(",")
            if item.strip()
        )
        return cls(
            provider=ProviderKind(os.getenv("FOREX_PROVIDER", "simulation").lower()),
            mode=OperatingMode(os.getenv("FOREX_MODE", "shadow").lower()),
            database_path=os.getenv("FOREX_DATABASE_PATH", "./forex_trader.db"),
            instruments=instruments,
            require_fundamentals=_bool(os.getenv("FOREX_REQUIRE_FUNDAMENTALS"), True),
            enable_paper_orders=_bool(os.getenv("FOREX_ENABLE_PAPER_ORDERS"), False),
            minimum_score=_decimal_env("FOREX_MINIMUM_SCORE", "0.66"),
            maximum_spread_pips=_decimal_env("FOREX_MAXIMUM_SPREAD_PIPS", "2.0"),
            maximum_slippage_pips=_decimal_env("FOREX_MAXIMUM_SLIPPAGE_PIPS", "0.5"),
            risk_fraction=_decimal_env("FOREX_RISK_FRACTION", "0.0015"),
            max_daily_loss_fraction=_decimal_env("FOREX_MAX_DAILY_LOSS_FRACTION", "0.01"),
            max_open_positions=int(os.getenv("FOREX_MAX_OPEN_POSITIONS", "3")),
            max_units=int(os.getenv("FOREX_MAX_UNITS", "100000")),
            max_gross_exposure_fraction=_decimal_env("FOREX_MAX_GROSS_EXPOSURE_FRACTION", "4"),
            max_currency_exposure_fraction=_decimal_env("FOREX_MAX_CURRENCY_EXPOSURE_FRACTION", "2"),
            auto_discover_currency_instruments=_bool(os.getenv("FOREX_AUTO_DISCOVER_CURRENCY_INSTRUMENTS"), False),
            api_token=os.getenv("FOREX_API_TOKEN") or None,
            oanda_token=os.getenv("OANDA_API_TOKEN") or None,
            oanda_account_id=os.getenv("OANDA_ACCOUNT_ID") or None,
            oanda_rest_url=os.getenv("OANDA_REST_URL", "https://api-fxpractice.oanda.com"),
            oanda_stream_url=os.getenv("OANDA_STREAM_URL", "https://stream-fxpractice.oanda.com"),
            oanda_timeout_seconds=float(os.getenv("OANDA_TIMEOUT_SECONDS", "10")),
        )

    def validate(self) -> list[str]:
        errors: list[str] = []
        if self.provider is ProviderKind.OANDA:
            if not self.oanda_token:
                errors.append("OANDA_API_TOKEN is required for the OANDA provider")
            parsed = urlparse(self.oanda_rest_url)
            if parsed.scheme != "https" or parsed.hostname != "api-fxpractice.oanda.com":
                errors.append("the OANDA provider is locked to https://api-fxpractice.oanda.com")
            stream = urlparse(self.oanda_stream_url)
            if stream.scheme != "https" or stream.hostname != "stream-fxpractice.oanda.com":
                errors.append("the OANDA stream is locked to https://stream-fxpractice.oanda.com")
            if self.enable_paper_orders and not self.oanda_account_id:
                errors.append("OANDA_ACCOUNT_ID is required when paper broker writes are enabled")
        if self.enable_paper_orders and self.mode is not OperatingMode.PAPER:
            errors.append("paper orders can only be enabled when FOREX_MODE=paper")
        if not self.instruments and not self.auto_discover_currency_instruments:
            errors.append("at least one instrument is required unless auto discovery is enabled")
        if not Decimal("0") <= self.minimum_score <= Decimal("1"):
            errors.append("FOREX_MINIMUM_SCORE must be between 0 and 1")
        if self.maximum_spread_pips <= 0 or self.maximum_slippage_pips <= 0:
            errors.append("spread/slippage limits must be positive")
        if not Decimal("0") < self.risk_fraction <= Decimal("0.02"):
            errors.append("FOREX_RISK_FRACTION must be greater than 0 and no more than 0.02")
        if not Decimal("0") < self.max_daily_loss_fraction <= Decimal("0.20"):
            errors.append("FOREX_MAX_DAILY_LOSS_FRACTION must be greater than 0 and no more than 0.20")
        if self.max_open_positions < 1 or self.max_units < 1:
            errors.append("position and unit limits must be positive")
        if self.max_gross_exposure_fraction <= 0 or self.max_currency_exposure_fraction <= 0:
            errors.append("portfolio exposure limits must be positive")
        return errors


def load_macro_file(
    path: str | Path | None,
    *,
    use_demo_defaults: bool = True,
) -> FundamentalBook:
    if path is None and use_demo_defaults:
        data = {
            "EUR": {"policy": "0.10", "inflation": "0.05", "growth": "0.10", "labor": "0.05", "news": "0", "confidence": "0.70"},
            "USD": {"policy": "-0.05", "inflation": "0", "growth": "0", "labor": "0", "news": "0", "confidence": "0.70"},
            "GBP": {"policy": "0.05", "inflation": "0.05", "growth": "0", "labor": "0", "news": "0", "confidence": "0.65"},
            "JPY": {"policy": "-0.20", "inflation": "-0.05", "growth": "-0.05", "labor": "0", "news": "0", "confidence": "0.65"},
        }
        as_of = datetime.now(UTC)
    elif path is None:
        data = {currency: {"confidence": "0"} for currency in ("EUR", "USD", "GBP", "JPY", "CHF", "CAD", "AUD", "NZD")}
        as_of = datetime(2000, 1, 1, tzinfo=UTC)
    else:
        data = json.loads(Path(path).read_text())
        as_of = datetime.now(UTC)
    snapshots = [
        CurrencyFundamentals(
            currency=currency,
            policy=Decimal(str(values.get("policy", 0))),
            inflation=Decimal(str(values.get("inflation", 0))),
            growth=Decimal(str(values.get("growth", 0))),
            labor=Decimal(str(values.get("labor", 0))),
            news=Decimal(str(values.get("news", 0))),
            confidence=Decimal(str(values.get("confidence", 0))),
            as_of=as_of,
        )
        for currency, values in data.items()
    ]
    return FundamentalBook(snapshots)


def build_engine(config: AppConfig, *, macro_file: str | None = None) -> TradingEngine:
    errors = config.validate()
    if errors:
        raise ValueError("; ".join(errors))
    repository = TradingRepository(config.database_path)
    seed_book = load_macro_file(macro_file, use_demo_defaults=config.provider is ProviderKind.SIMULATION)
    fundamentals = PointInTimeFundamentalBook(
        repository.macro_observations(),
        seeds=seed_book.snapshots(),
    )

    if config.provider is ProviderKind.OANDA:
        assert config.oanda_token is not None
        provider = SafeOandaPracticeClient(
            token=config.oanda_token,
            account_id=config.oanda_account_id,
            rest_url=config.oanda_rest_url,
            stream_url=config.oanda_stream_url,
            timeout_seconds=config.oanda_timeout_seconds,
        )
        broker = provider
    else:
        provider = SyntheticMarketData(direction="long")
        broker = SimulatedPaperBroker(provider)
    return TradingEngine(
        market_data=provider,
        broker=broker,
        repository=repository,
        fundamentals=fundamentals,
        fusion_policy=SignalFusionPolicy(
            minimum_score=config.minimum_score,
            maximum_spread_pips=config.maximum_spread_pips,
            require_fundamentals=config.require_fundamentals,
        ),
        risk_policy=RiskPolicy(
            risk_fraction=config.risk_fraction,
            max_daily_loss_fraction=config.max_daily_loss_fraction,
            max_open_positions=config.max_open_positions,
            max_units=config.max_units,
            max_gross_exposure_fraction=config.max_gross_exposure_fraction,
            max_currency_exposure_fraction=config.max_currency_exposure_fraction,
        ),
        mode=config.mode,
        enable_paper_orders=config.enable_paper_orders,
        cost_model=SessionCostModel(repository.cost_samples(), minimum_samples=30),
        maximum_slippage_pips=config.maximum_slippage_pips,
    )
