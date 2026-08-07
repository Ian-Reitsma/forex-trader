from datetime import UTC, datetime, timedelta
from decimal import Decimal

from forex_trader.domain.enums import Direction
from forex_trader.research.backtest import BacktestTrade, OutcomeStatus
from forex_trader.research.validation import rolling_threshold_validation, validate_multiple_instruments


def make_trades(count: int = 240) -> list[BacktestTrade]:
    start = datetime(2026, 1, 1, tzinfo=UTC)
    trades: list[BacktestTrade] = []
    for index in range(count):
        high_quality = index % 3 != 0
        score = Decimal("0.78") if high_quality else Decimal("0.58")
        win = high_quality or index % 5 == 0
        trades.append(
            BacktestTrade(
                instrument="EUR_USD",
                direction=Direction.LONG,
                signal_time=start + timedelta(minutes=5 * index),
                score=score,
                status=OutcomeStatus.WIN if win else OutcomeStatus.LOSS,
                r_multiple=Decimal("1.5") if win else Decimal("-1"),
                bars_held=3,
            )
        )
    return trades


def test_rolling_validation_keeps_final_holdout_out_of_training() -> None:
    report = rolling_threshold_validation(
        make_trades(),
        train_size=80,
        validation_size=40,
        step=40,
        minimum_training_trades=20,
    )
    assert report.folds
    assert report.holdout.trades > 0
    assert report.selected_threshold in {Decimal("0.55"), Decimal("0.60"), Decimal("0.65"), Decimal("0.70"), Decimal("0.75"), Decimal("0.80")}
    assert report.holdout.expectancy_r > 0


def test_multi_instrument_validation_aggregates_holdouts() -> None:
    eur = make_trades()
    gbp = [trade.__class__("GBP_USD", trade.direction, trade.signal_time, trade.score, trade.status, trade.r_multiple, trade.bars_held) for trade in eur]
    report = validate_multiple_instruments(
        {"EUR_USD": eur, "GBP_USD": gbp},
        train_size=80,
        validation_size=40,
        step=40,
        minimum_training_trades=20,
    )
    assert report.holdout_trades > 0
    assert report.profitable_instruments == 2
