from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import uuid4

from forex_trader.domain.enums import DecisionDisposition, Direction
from forex_trader.domain.models import Quote, TradeCandidate
from forex_trader.research.backtest import BacktestTrade, OutcomeStatus
from forex_trader.research.portfolio_risk_replay import (
    HistoricalPortfolioRiskConfig,
    HistoricalPortfolioRiskReplay,
    RiskReplayOpportunity,
)

START = datetime(2026, 6, 9, 14, 0, tzinfo=UTC)
MARKS = {
    "EUR_USD": Decimal("1.1000"),
    "GBP_USD": Decimal("1.2500"),
    "USD_JPY": Decimal("150.00"),
}


def _mark(instrument: str, _instant: datetime) -> Decimal | None:
    return MARKS.get(instrument.upper())


def _conversion(source: str, target: str, _instant: datetime) -> Decimal | None:
    source = source.upper()
    target = target.upper()
    if source == target:
        return Decimal("1")
    if target != "USD":
        return None
    if source == "EUR":
        return MARKS["EUR_USD"]
    if source == "GBP":
        return MARKS["GBP_USD"]
    if source == "JPY":
        return Decimal("1") / MARKS["USD_JPY"]
    return None


def _config(**overrides: object) -> HistoricalPortfolioRiskConfig:
    values: dict[str, object] = {
        "starting_balance": Decimal("100000"),
        "max_units": 1_000_000,
        "max_gross_exposure_fraction": Decimal("100"),
        "max_currency_exposure_fraction": Decimal("100"),
        "max_macro_factor_exposure_fraction": Decimal("100"),
        "max_reserved_risk_fraction": Decimal("0.02"),
        "max_open_positions": 10,
    }
    values.update(overrides)
    return HistoricalPortfolioRiskConfig(**values)  # type: ignore[arg-type]


def _opportunity(
    *,
    instant: datetime,
    instrument: str = "EUR_USD",
    direction: Direction = Direction.LONG,
    r_multiple: str = "1",
    duration_minutes: int = 30,
) -> RiskReplayOpportunity:
    mid = MARKS[instrument]
    spread = Decimal("0.0001") if not instrument.endswith("JPY") else Decimal("0.01")
    stop_distance = Decimal("0.0010") if not instrument.endswith("JPY") else Decimal("0.10")
    reward_distance = stop_distance * Decimal("1.5")
    if direction is Direction.LONG:
        bid = mid - spread
        ask = mid
        entry = ask
        stop = entry - stop_distance
        target = entry + reward_distance
    else:
        bid = mid
        ask = mid + spread
        entry = bid
        stop = entry + stop_distance
        target = entry - reward_distance
    candidate = TradeCandidate(
        candidate_id=uuid4(),
        instrument=instrument,
        direction=direction,
        disposition=DecisionDisposition.TRADE,
        score=Decimal("0.80"),
        entry_price=entry,
        stop_loss=stop,
        take_profit=target,
        technical_score=Decimal("0.80"),
        fundamental_score=Decimal("0"),
        fundamental_confidence=Decimal("0"),
        reasons=(),
        signal_time=instant,
        execution_key=f"test-{instrument}-{instant.isoformat()}",
        expires_at=instant + timedelta(minutes=5),
    )
    realized = Decimal(r_multiple)
    trade = BacktestTrade(
        instrument=instrument,
        direction=direction,
        signal_time=instant,
        score=Decimal("0.80"),
        status=OutcomeStatus.WIN if realized > 0 else OutcomeStatus.LOSS,
        r_multiple=realized,
        bars_held=max(1, duration_minutes // 5),
        entry_fill=entry,
        exit_fill=target if realized > 0 else stop,
    )
    return RiskReplayOpportunity(
        candidate=candidate,
        quote=Quote(instrument, bid, ask, instant),
        trade=trade,
        entry_time=instant,
        exit_time=instant + timedelta(minutes=duration_minutes),
    )


def test_max_open_position_limit_matches_runtime_admission() -> None:
    replay = HistoricalPortfolioRiskReplay(
        config=_config(max_open_positions=1),
        mark_price_at=_mark,
        conversion_rate_at=_conversion,
    )
    first = _opportunity(instant=START, duration_minutes=60)
    overlapping = _opportunity(instant=START + timedelta(minutes=10), instrument="GBP_USD")
    after_close = _opportunity(instant=START + timedelta(minutes=70), instrument="GBP_USD")

    report = replay.run((first, overlapping, after_close))

    assert report.admitted_trades == 2
    assert report.denied_trades == 1
    assert report.maximum_concurrent_positions == 1
    assert any("maximum open-position count reached" in reason for reason in report.denial_reasons)


def test_closed_loss_is_not_visible_before_its_exit_time() -> None:
    replay = HistoricalPortfolioRiskReplay(
        config=_config(max_daily_loss_fraction=Decimal("0.001")),
        mark_price_at=_mark,
        conversion_rate_at=_conversion,
    )
    future_loss = _opportunity(instant=START, r_multiple="-1", duration_minutes=60)
    before_exit = _opportunity(instant=START + timedelta(minutes=10), instrument="GBP_USD")

    report = replay.run((future_loss, before_exit))

    assert report.admitted_trades == 2
    assert report.denied_trades == 0


def test_realized_loss_blocks_later_same_risk_day() -> None:
    replay = HistoricalPortfolioRiskReplay(
        config=_config(max_daily_loss_fraction=Decimal("0.001")),
        mark_price_at=_mark,
        conversion_rate_at=_conversion,
    )
    loss = _opportunity(instant=START, r_multiple="-1", duration_minutes=10)
    later = _opportunity(instant=START + timedelta(minutes=20), instrument="GBP_USD")

    report = replay.run((loss, later))

    assert report.admitted_trades == 1
    assert report.denied_trades == 1
    assert any("daily marked-loss limit reached" in reason for reason in report.denial_reasons)


def test_stressed_reserved_risk_cap_blocks_overcommitment() -> None:
    replay = HistoricalPortfolioRiskReplay(
        config=_config(max_reserved_risk_fraction=Decimal("0.003")),
        mark_price_at=_mark,
        conversion_rate_at=_conversion,
    )
    first = _opportunity(instant=START, duration_minutes=60)
    second = _opportunity(instant=START + timedelta(minutes=5), instrument="GBP_USD")

    report = replay.run((first, second))

    assert report.admitted_trades == 1
    assert report.denied_trades == 1
    assert any("stressed-risk cap" in reason for reason in report.denial_reasons)


def test_gross_currency_exposure_uses_production_risk_veto() -> None:
    replay = HistoricalPortfolioRiskReplay(
        config=_config(max_gross_exposure_fraction=Decimal("3.0")),
        mark_price_at=_mark,
        conversion_rate_at=_conversion,
    )

    report = replay.run((_opportunity(instant=START),))

    assert report.admitted_trades == 0
    assert report.denied_trades == 1
    assert any("gross portfolio currency exposure" in reason for reason in report.denial_reasons)


def test_macro_factor_concentration_uses_production_guard() -> None:
    replay = HistoricalPortfolioRiskReplay(
        config=_config(max_macro_factor_exposure_fraction=Decimal("1.0")),
        mark_price_at=_mark,
        conversion_rate_at=_conversion,
    )

    report = replay.run((_opportunity(instant=START),))

    assert report.admitted_trades == 0
    assert report.denied_trades == 1
    assert any("macro factor exposure limit exceeded" in reason for reason in report.denial_reasons)
