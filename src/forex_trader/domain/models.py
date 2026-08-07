from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4

from forex_trader.domain.enums import (
    DecisionDisposition,
    Direction,
    OrderStatus,
    RiskDisposition,
)


def utc_now() -> datetime:
    return datetime.now(UTC)


def decimal(value: Decimal | str | float | int) -> Decimal:
    return value if isinstance(value, Decimal) else Decimal(str(value))


@dataclass(frozen=True, slots=True)
class Candle:
    time: datetime
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    volume: int = 0
    complete: bool = True

    def __post_init__(self) -> None:
        if self.time.tzinfo is None:
            raise ValueError("candle time must be timezone-aware")
        if self.high < max(self.open, self.close) or self.low > min(self.open, self.close):
            raise ValueError("invalid OHLC relationship")
        if self.high < self.low:
            raise ValueError("high must be >= low")


@dataclass(frozen=True, slots=True)
class Quote:
    instrument: str
    bid: Decimal
    ask: Decimal
    time: datetime

    def __post_init__(self) -> None:
        if self.ask < self.bid:
            raise ValueError("ask must be >= bid")
        if self.time.tzinfo is None:
            raise ValueError("quote time must be timezone-aware")

    @property
    def mid(self) -> Decimal:
        return (self.bid + self.ask) / Decimal("2")

    @property
    def spread(self) -> Decimal:
        return self.ask - self.bid


@dataclass(frozen=True, slots=True)
class AccountSnapshot:
    account_id: str
    currency: str
    balance: Decimal
    nav: Decimal
    margin_used: Decimal = Decimal("0")
    margin_available: Decimal = Decimal("0")
    unrealized_pl: Decimal = Decimal("0")
    open_position_count: int = 0
    realized_pl_today: Decimal = Decimal("0")


@dataclass(frozen=True, slots=True)
class InstrumentSpec:
    name: str
    display_precision: int
    pip_location: int
    trade_units_precision: int
    minimum_trade_size: Decimal
    maximum_order_units: Decimal | None = None

    @property
    def pip_size(self) -> Decimal:
        return Decimal(1).scaleb(self.pip_location)

    def format_price(self, value: Decimal) -> str:
        quantum = Decimal(1).scaleb(-self.display_precision)
        rounded = value.quantize(quantum)
        return f"{rounded:.{self.display_precision}f}"

    def format_units(self, value: int | Decimal) -> str:
        decimal_value = Decimal(value)
        quantum = Decimal(1).scaleb(-self.trade_units_precision)
        rounded = decimal_value.quantize(quantum)
        if self.trade_units_precision == 0:
            return str(int(rounded))
        return f"{rounded:.{self.trade_units_precision}f}"


@dataclass(frozen=True, slots=True)
class CurrencyFundamentals:
    currency: str
    policy: Decimal = Decimal("0")
    inflation: Decimal = Decimal("0")
    growth: Decimal = Decimal("0")
    labor: Decimal = Decimal("0")
    news: Decimal = Decimal("0")
    confidence: Decimal = Decimal("0")
    as_of: datetime = field(default_factory=utc_now)

    @property
    def score(self) -> Decimal:
        raw = (
            self.policy * Decimal("0.35")
            + self.inflation * Decimal("0.20")
            + self.growth * Decimal("0.15")
            + self.labor * Decimal("0.15")
            + self.news * Decimal("0.15")
        )
        return max(Decimal("-1"), min(Decimal("1"), raw))


@dataclass(frozen=True, slots=True)
class FundamentalAssessment:
    instrument: str
    base_score: Decimal
    quote_score: Decimal
    differential: Decimal
    confidence: Decimal
    reasons: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class TechnicalAssessment:
    instrument: str
    direction: Direction
    score: Decimal
    atr: Decimal
    rsi: Decimal
    entry_reference: Decimal
    stop_reference: Decimal | None
    take_profit_reference: Decimal | None
    reasons: tuple[str, ...]
    signal_time: datetime = field(default_factory=utc_now)
    liquidity_sweep: bool = False
    displacement: bool = False
    trend_strength: Decimal = Decimal("0")
    reward_risk: Decimal = Decimal("0")


@dataclass(frozen=True, slots=True)
class TradeCandidate:
    candidate_id: UUID
    instrument: str
    direction: Direction
    disposition: DecisionDisposition
    score: Decimal
    entry_price: Decimal | None
    stop_loss: Decimal | None
    take_profit: Decimal | None
    technical_score: Decimal
    fundamental_score: Decimal
    reasons: tuple[str, ...]
    signal_time: datetime = field(default_factory=utc_now)
    execution_key: str = ""
    created_at: datetime = field(default_factory=utc_now)


@dataclass(frozen=True, slots=True)
class RiskAuthorization:
    authorization_id: UUID
    candidate_id: UUID
    disposition: RiskDisposition
    units: int
    risk_amount: Decimal
    reasons: tuple[str, ...]
    created_at: datetime = field(default_factory=utc_now)


@dataclass(frozen=True, slots=True)
class OrderRequest:
    client_order_id: str
    instrument: str
    direction: Direction
    units: int
    stop_loss: Decimal
    take_profit: Decimal
    execution_key: str = ""


@dataclass(frozen=True, slots=True)
class OrderResult:
    client_order_id: str
    provider_order_id: str | None
    status: OrderStatus
    instrument: str
    units: int
    fill_price: Decimal | None
    provider_trade_id: str | None = None
    raw: dict[str, Any] = field(default_factory=dict)
    created_at: datetime = field(default_factory=utc_now)


@dataclass(frozen=True, slots=True)
class DecisionTrace:
    trace_id: UUID
    instrument: str
    candidate: TradeCandidate
    risk: RiskAuthorization | None
    order: OrderResult | None
    quote: Quote
    created_at: datetime = field(default_factory=utc_now)

    @classmethod
    def create(
        cls,
        instrument: str,
        candidate: TradeCandidate,
        quote: Quote,
        risk: RiskAuthorization | None = None,
        order: OrderResult | None = None,
    ) -> "DecisionTrace":
        return cls(uuid4(), instrument, candidate, risk, order, quote)


def jsonable(value: Any) -> Any:
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, datetime):
        return value.astimezone(UTC).isoformat()
    if isinstance(value, UUID):
        return str(value)
    if hasattr(value, "value") and isinstance(value.value, str):
        return value.value
    if isinstance(value, tuple):
        return [jsonable(v) for v in value]
    if isinstance(value, list):
        return [jsonable(v) for v in value]
    if isinstance(value, dict):
        return {str(k): jsonable(v) for k, v in value.items()}
    if hasattr(value, "__dataclass_fields__"):
        return {k: jsonable(v) for k, v in asdict(value).items()}
    return value
