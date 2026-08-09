from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from typing import Callable, Iterable

from forex_trader.domain.correlation_risk import CorrelationRiskGuard
from forex_trader.domain.enums import Direction, RiskDisposition
from forex_trader.domain.macro_factor_risk import MacroFactorClusterGuard, default_macro_factor_map
from forex_trader.domain.models import AccountSnapshot, Candle, Quote, RiskAuthorization, TradeCandidate
from forex_trader.domain.portfolio import OpenPosition
from forex_trader.domain.risk_advanced import EnhancedRiskPolicy
from forex_trader.domain.risk_day import fx_risk_day_key
from forex_trader.research.backtest import BacktestTrade

MarkPriceAt = Callable[[str, datetime], Decimal | None]
ConversionRateAt = Callable[[str, str, datetime], Decimal | None]
HistoricalCandleLoader = Callable[[str, str, datetime, int], list[Candle]]


@dataclass(frozen=True, slots=True)
class HistoricalPortfolioRiskConfig:
    """Runtime-equivalent risk limits for historical portfolio admission.

    The defaults intentionally mirror ``AppConfig``/``EnhancedRiskPolicy``. Starting
    balance is explicit because unit caps, gross exposure and currency exposure are
    account-size dependent even when R-multiple expectancy is not.
    """

    starting_balance: Decimal = Decimal("100000")
    account_currency: str = "USD"
    risk_fraction: Decimal = Decimal("0.0015")
    max_daily_loss_fraction: Decimal = Decimal("0.01")
    max_open_positions: int = 3
    max_units: int = 100_000
    max_gross_exposure_fraction: Decimal = Decimal("4")
    max_currency_exposure_fraction: Decimal = Decimal("2")
    max_drawdown_fraction: Decimal = Decimal("0.10")
    max_loss_streak: int = 6
    max_reserved_risk_fraction: Decimal = Decimal("0.02")
    gap_stress_multiplier: Decimal = Decimal("1.25")
    max_macro_factor_exposure_fraction: Decimal = Decimal("2.5")
    require_macro_factor_classification: bool = True
    max_signed_correlation: float = 0.85
    correlation_minimum_observations: int = 40
    correlation_lookback: int = 81
    correlation_granularity: str = "H1"
    margin_rate: Decimal | None = None

    def __post_init__(self) -> None:
        if self.starting_balance <= 0:
            raise ValueError("starting_balance must be positive")
        if self.correlation_lookback < self.correlation_minimum_observations + 1:
            raise ValueError("correlation lookback must exceed minimum observations")


@dataclass(frozen=True, slots=True)
class RiskReplayOpportunity:
    """One historical trade hypothesis with the exact runtime risk inputs preserved."""

    candidate: TradeCandidate
    quote: Quote
    trade: BacktestTrade
    entry_time: datetime
    exit_time: datetime

    def __post_init__(self) -> None:
        if self.entry_time.tzinfo is None or self.exit_time.tzinfo is None:
            raise ValueError("replay timestamps must be timezone-aware")
        if self.quote.time > self.entry_time or self.entry_time > self.exit_time:
            raise ValueError("expected quote.time <= entry_time <= exit_time")
        if self.quote.instrument.upper() != self.candidate.instrument.upper():
            raise ValueError("quote and candidate instruments must match")
        if self.trade.instrument.upper() != self.candidate.instrument.upper():
            raise ValueError("trade and candidate instruments must match")
        if self.trade.direction is not self.candidate.direction:
            raise ValueError("trade and candidate directions must match")
        if self.candidate.entry_price is None or self.candidate.stop_loss is None:
            raise ValueError("risk replay requires executable entry and stop geometry")


@dataclass(frozen=True, slots=True)
class RiskReplayDecision:
    opportunity: RiskReplayOpportunity
    authorization: RiskAuthorization

    @property
    def admitted(self) -> bool:
        return self.authorization.disposition is RiskDisposition.GRANTED


@dataclass(frozen=True, slots=True)
class HistoricalPortfolioRiskReport:
    starting_balance: Decimal
    ending_balance: Decimal
    total_return: Decimal
    admitted_trades: int
    denied_trades: int
    maximum_concurrent_positions: int
    maximum_equity_drawdown: Decimal
    correlation_enforced: bool
    decisions: tuple[RiskReplayDecision, ...]
    denial_reasons: dict[str, int] = field(default_factory=dict)

    @property
    def admitted_opportunities(self) -> tuple[RiskReplayOpportunity, ...]:
        return tuple(item.opportunity for item in self.decisions if item.admitted)


@dataclass(slots=True)
class _OpenReplayTrade:
    opportunity: RiskReplayOpportunity
    authorization: RiskAuthorization
    position: OpenPosition


class _PointInTimeCorrelationContext:
    def __init__(
        self,
        loader: HistoricalCandleLoader,
        *,
        granularity: str,
        lookback: int,
        minimum_observations: int,
        maximum_signed_correlation: float,
    ) -> None:
        self.loader = loader
        self.as_of: datetime | None = None
        self.guard = CorrelationRiskGuard(
            self._load,
            semantic_granularity=granularity,
            lookback=lookback,
            minimum_observations=minimum_observations,
            maximum_signed_correlation=maximum_signed_correlation,
            fail_closed=True,
        )

    def _load(self, instrument: str, granularity: str, count: int) -> list[Candle]:
        if self.as_of is None:
            raise RuntimeError("historical correlation context is missing as_of")
        candles = self.loader(instrument, granularity, self.as_of, count)
        # The adapter enforces the point-in-time contract even if a caller accidentally
        # returns later bars. Candle timestamps are bar starts; incomplete/future bars
        # therefore never reach the runtime correlation guard.
        eligible = [item for item in candles if item.complete and item.time < self.as_of]
        return eligible[-count:]


class HistoricalPortfolioRiskReplay:
    """Replay historical opportunities through the production risk policy causally.

    Strategy selection and outcome generation happen upstream. This layer answers a
    narrower question: given the hypotheses that existed at each historical instant,
    which ones could the runtime portfolio risk system actually have authorized?

    Closed-trade P/L is not visible until ``exit_time``. Open positions are marked at
    each later decision using caller-supplied point-in-time prices. The exact production
    ``EnhancedRiskPolicy`` performs the admission decision, including position count,
    marked daily loss, unit sizing, currency/gross exposure, correlation (when a causal
    candle loader is supplied), macro-factor concentration, drawdown/loss-streak state,
    and stressed reserved-risk limits.
    """

    def __init__(
        self,
        *,
        config: HistoricalPortfolioRiskConfig = HistoricalPortfolioRiskConfig(),
        mark_price_at: MarkPriceAt,
        conversion_rate_at: ConversionRateAt,
        correlation_candle_loader: HistoricalCandleLoader | None = None,
    ) -> None:
        self.config = config
        self.mark_price_at = mark_price_at
        self.conversion_rate_at = conversion_rate_at
        self.correlation = (
            _PointInTimeCorrelationContext(
                correlation_candle_loader,
                granularity=config.correlation_granularity,
                lookback=config.correlation_lookback,
                minimum_observations=config.correlation_minimum_observations,
                maximum_signed_correlation=config.max_signed_correlation,
            )
            if correlation_candle_loader is not None
            else None
        )

    def run(self, opportunities: Iterable[RiskReplayOpportunity]) -> HistoricalPortfolioRiskReport:
        ordered = tuple(sorted(opportunities, key=lambda item: (item.quote.time, item.candidate.instrument)))
        balance = self.config.starting_balance
        peak_nav = balance
        maximum_drawdown = Decimal("0")
        loss_streak = 0
        open_trades: list[_OpenReplayTrade] = []
        realized_by_risk_day: dict[str, Decimal] = {}
        decisions: list[RiskReplayDecision] = []
        maximum_concurrent = 0

        current_nav = balance

        def risk_state(_account_id: str, _nav: Decimal) -> dict[str, object]:
            reserved = sum((item.authorization.risk_amount for item in open_trades), Decimal("0"))
            drawdown = Decimal("0") if peak_nav <= 0 else max(Decimal("0"), (peak_nav - current_nav) / peak_nav)
            return {
                "drawdown_fraction": drawdown,
                "loss_streak": loss_streak,
                "reserved_risk": reserved,
                "pending_risk": Decimal("0"),
            }

        macro_guard = MacroFactorClusterGuard(
            default_macro_factor_map(),
            maximum_factor_exposure_fraction=self.config.max_macro_factor_exposure_fraction,
            require_classification=self.config.require_macro_factor_classification,
        )
        risk_policy = EnhancedRiskPolicy(
            risk_fraction=self.config.risk_fraction,
            max_daily_loss_fraction=self.config.max_daily_loss_fraction,
            max_open_positions=self.config.max_open_positions,
            max_units=self.config.max_units,
            max_gross_exposure_fraction=self.config.max_gross_exposure_fraction,
            max_currency_exposure_fraction=self.config.max_currency_exposure_fraction,
            correlation_guard=self.correlation.guard if self.correlation is not None else None,
            macro_factor_guard=macro_guard,
            state_provider=risk_state,
            max_drawdown_fraction=self.config.max_drawdown_fraction,
            max_loss_streak=self.config.max_loss_streak,
            max_reserved_risk_fraction=self.config.max_reserved_risk_fraction,
            gap_stress_multiplier=self.config.gap_stress_multiplier,
            environment="historical-replay",
            risk_policy_version="historical-runtime-parity-v1",
        )

        for opportunity in ordered:
            instant = opportunity.quote.time

            still_open: list[_OpenReplayTrade] = []
            for active in sorted(open_trades, key=lambda item: item.opportunity.exit_time):
                if active.opportunity.exit_time > instant:
                    still_open.append(active)
                    continue
                pnl = active.authorization.risk_amount * active.opportunity.trade.r_multiple
                balance += pnl
                key = fx_risk_day_key(active.opportunity.exit_time)
                realized_by_risk_day[key] = realized_by_risk_day.get(key, Decimal("0")) + pnl
                if pnl < 0:
                    loss_streak += 1
                elif pnl > 0:
                    loss_streak = 0
            open_trades = still_open

            def mark_price(instrument: str) -> Decimal | None:
                return self.mark_price_at(instrument.upper(), instant)

            def conversion_rate(source: str, target: str) -> Decimal | None:
                if source.upper() == target.upper():
                    return Decimal("1")
                return self.conversion_rate_at(source.upper(), target.upper(), instant)

            unrealized = self._unrealized_pl(open_trades, instant, conversion_rate)
            current_nav = balance + unrealized
            peak_nav = max(peak_nav, current_nav)
            if peak_nav > 0:
                maximum_drawdown = max(maximum_drawdown, max(Decimal("0"), (peak_nav - current_nav) / peak_nav))

            if self.correlation is not None:
                self.correlation.as_of = instant

            account = AccountSnapshot(
                account_id="historical-replay",
                currency=self.config.account_currency.upper(),
                balance=balance,
                nav=current_nav,
                unrealized_pl=unrealized,
                open_position_count=len(open_trades),
                realized_pl_today=realized_by_risk_day.get(fx_risk_day_key(instant), Decimal("0")),
                margin_available=max(Decimal("0"), current_nav),
            )
            authorization = risk_policy.authorize(
                opportunity.candidate,
                account,
                opportunity.quote,
                positions=(item.position for item in open_trades),
                conversion_rate=conversion_rate,
                mark_price=mark_price,
                margin_rate=self.config.margin_rate,
            )
            decisions.append(RiskReplayDecision(opportunity, authorization))
            if authorization.disposition is not RiskDisposition.GRANTED:
                continue

            signed_units = Decimal(
                authorization.units if opportunity.candidate.direction is Direction.LONG else -authorization.units
            )
            entry_price = opportunity.candidate.entry_price
            assert entry_price is not None
            position = OpenPosition(
                instrument=opportunity.candidate.instrument,
                long_units=signed_units if signed_units > 0 else Decimal("0"),
                short_units=signed_units if signed_units < 0 else Decimal("0"),
                long_average_price=entry_price if signed_units > 0 else None,
                short_average_price=entry_price if signed_units < 0 else None,
            )
            open_trades.append(_OpenReplayTrade(opportunity, authorization, position))
            maximum_concurrent = max(maximum_concurrent, len(open_trades))

        # Realize every admitted trade after the final decision so ending balance is a
        # complete campaign result. This occurs only after all admission decisions are done,
        # so terminal outcomes cannot leak backward into earlier risk authorization.
        for active in sorted(open_trades, key=lambda item: item.opportunity.exit_time):
            pnl = active.authorization.risk_amount * active.opportunity.trade.r_multiple
            balance += pnl
            peak_nav = max(peak_nav, balance)
            if peak_nav > 0:
                maximum_drawdown = max(maximum_drawdown, max(Decimal("0"), (peak_nav - balance) / peak_nav))

        counts: Counter[str] = Counter()
        for item in decisions:
            if item.admitted:
                continue
            reason = item.authorization.reasons[0] if item.authorization.reasons else "unspecified risk denial"
            counts[reason] += 1

        return HistoricalPortfolioRiskReport(
            starting_balance=self.config.starting_balance,
            ending_balance=balance,
            total_return=balance / self.config.starting_balance - Decimal("1"),
            admitted_trades=sum(item.admitted for item in decisions),
            denied_trades=sum(not item.admitted for item in decisions),
            maximum_concurrent_positions=maximum_concurrent,
            maximum_equity_drawdown=maximum_drawdown,
            correlation_enforced=self.correlation is not None,
            decisions=tuple(decisions),
            denial_reasons=dict(counts),
        )

    def _unrealized_pl(
        self,
        open_trades: Iterable[_OpenReplayTrade],
        instant: datetime,
        conversion_rate: Callable[[str, str], Decimal | None],
    ) -> Decimal:
        total = Decimal("0")
        account = self.config.account_currency.upper()
        for active in open_trades:
            position = active.position
            mark = self.mark_price_at(position.instrument.upper(), instant)
            if mark is None or mark <= 0:
                # Runtime exposure logic fails closed when a required mark is unavailable;
                # leave NAV neutral here and let authorization reject on pricing below.
                continue
            _, quote_currency = position.instrument.upper().split("_", maxsplit=1)
            rate = conversion_rate(quote_currency, account)
            if rate is None or rate <= 0:
                continue
            if position.net_units > 0 and position.long_average_price is not None:
                total += position.net_units * (mark - position.long_average_price) * rate
            elif position.net_units < 0 and position.short_average_price is not None:
                total += abs(position.net_units) * (position.short_average_price - mark) * rate
        return total
