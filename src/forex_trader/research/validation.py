from __future__ import annotations

from dataclasses import dataclass, replace
from decimal import Decimal

from forex_trader.research.backtest import BacktestReport, BacktestTrade, optimize_score_threshold, summarize_trades


DEFAULT_THRESHOLDS = (
    Decimal("0.55"),
    Decimal("0.60"),
    Decimal("0.65"),
    Decimal("0.70"),
    Decimal("0.75"),
    Decimal("0.80"),
)


@dataclass(frozen=True, slots=True)
class ValidationFold:
    train_start: int
    train_end: int
    validation_start: int
    validation_end: int
    selected_threshold: Decimal
    training: BacktestReport
    validation: BacktestReport


@dataclass(frozen=True, slots=True)
class RollingValidationReport:
    folds: tuple[ValidationFold, ...]
    selected_threshold: Decimal
    development: BacktestReport
    holdout: BacktestReport
    holdout_fraction: Decimal


@dataclass(frozen=True, slots=True)
class MultiInstrumentValidation:
    by_instrument: dict[str, RollingValidationReport]
    selected_threshold: Decimal
    holdout_trades: int
    holdout_win_rate: Decimal
    holdout_expectancy_r: Decimal
    profitable_instruments: int


def rolling_threshold_validation(
    trades: list[BacktestTrade],
    *,
    thresholds: tuple[Decimal, ...] = DEFAULT_THRESHOLDS,
    train_size: int = 80,
    validation_size: int = 40,
    step: int = 40,
    minimum_training_trades: int = 20,
    holdout_fraction: Decimal = Decimal("0.20"),
) -> RollingValidationReport:
    if not trades:
        raise ValueError("at least one trade is required")
    if train_size < 1 or validation_size < 1 or step < 1:
        raise ValueError("window sizes and step must be positive")
    if not Decimal("0.10") <= holdout_fraction <= Decimal("0.50"):
        raise ValueError("holdout_fraction must be between 0.10 and 0.50")
    chronological = sorted(trades, key=lambda trade: trade.signal_time)
    holdout_count = max(1, int(Decimal(len(chronological)) * holdout_fraction))
    development = chronological[:-holdout_count]
    holdout = chronological[-holdout_count:]
    if len(development) < train_size + validation_size:
        raise ValueError("not enough development trades for one train/validation fold")

    folds: list[ValidationFold] = []
    start = 0
    while start + train_size + validation_size <= len(development):
        train = development[start : start + train_size]
        validation = development[start + train_size : start + train_size + validation_size]
        selected = optimize_score_threshold(
            train,
            thresholds=thresholds,
            minimum_trades=min(minimum_training_trades, len(train)),
        )
        assert selected.minimum_score is not None
        validation_report = summarize_trades(validation, minimum_score=selected.minimum_score)
        folds.append(
            ValidationFold(
                train_start=start,
                train_end=start + train_size,
                validation_start=start + train_size,
                validation_end=start + train_size + validation_size,
                selected_threshold=selected.minimum_score,
                training=selected,
                validation=validation_report,
            )
        )
        start += step
    if not folds:
        raise ValueError("no rolling folds were produced")

    candidate_thresholds = sorted({fold.selected_threshold for fold in folds})
    scored: list[tuple[Decimal, Decimal, Decimal, Decimal]] = []
    for threshold in candidate_thresholds:
        reports = [
            summarize_trades(development[fold.validation_start : fold.validation_end], minimum_score=threshold)
            for fold in folds
        ]
        total_trades = sum(report.trades for report in reports)
        if total_trades == 0:
            continue
        expectancy = sum((report.expectancy_r * Decimal(report.trades) for report in reports), Decimal("0")) / Decimal(total_trades)
        wins = sum(report.wins for report in reports)
        win_rate = Decimal(wins) / Decimal(total_trades)
        drawdown = max(report.max_drawdown_r for report in reports)
        scored.append((threshold, expectancy, win_rate, -drawdown))
    if not scored:
        raise ValueError("validation folds produced no eligible threshold")
    selected_threshold = max(scored, key=lambda row: (row[1], row[2], row[3]))[0]
    return RollingValidationReport(
        folds=tuple(folds),
        selected_threshold=selected_threshold,
        development=summarize_trades(development, minimum_score=selected_threshold),
        holdout=summarize_trades(holdout, minimum_score=selected_threshold),
        holdout_fraction=holdout_fraction,
    )


def validate_multiple_instruments(
    trades_by_instrument: dict[str, list[BacktestTrade]],
    *,
    thresholds: tuple[Decimal, ...] = DEFAULT_THRESHOLDS,
    train_size: int = 80,
    validation_size: int = 40,
    step: int = 40,
    minimum_training_trades: int = 20,
    holdout_fraction: Decimal = Decimal("0.20"),
) -> MultiInstrumentValidation:
    """Select one global threshold that the production engine can actually deploy.

    Pair-specific fold selections are used only to define chronological development
    windows. The final threshold is chosen from pooled validation folds across pairs;
    untouched per-pair holdouts are then evaluated with that same global threshold.
    """
    if not trades_by_instrument:
        raise ValueError("at least one instrument is required")
    local_reports = {
        instrument: rolling_threshold_validation(
            trades,
            thresholds=thresholds,
            train_size=train_size,
            validation_size=validation_size,
            step=step,
            minimum_training_trades=minimum_training_trades,
            holdout_fraction=holdout_fraction,
        )
        for instrument, trades in sorted(trades_by_instrument.items())
    }

    scored: list[tuple[Decimal, Decimal, Decimal, Decimal, int]] = []
    for threshold in thresholds:
        reports: list[BacktestReport] = []
        for instrument, local in local_reports.items():
            chronological = sorted(trades_by_instrument[instrument], key=lambda trade: trade.signal_time)
            holdout_count = max(1, int(Decimal(len(chronological)) * holdout_fraction))
            development = chronological[:-holdout_count]
            for fold in local.folds:
                reports.append(
                    summarize_trades(
                        development[fold.validation_start : fold.validation_end],
                        minimum_score=threshold,
                    )
                )
        total_trades = sum(report.trades for report in reports)
        if total_trades < minimum_training_trades:
            continue
        total_r = sum((report.total_r for report in reports), Decimal("0"))
        wins = sum(report.wins for report in reports)
        drawdown = max((report.max_drawdown_r for report in reports), default=Decimal("0"))
        scored.append(
            (
                threshold,
                total_r / Decimal(total_trades),
                Decimal(wins) / Decimal(total_trades),
                -drawdown,
                total_trades,
            )
        )
    if not scored:
        raise ValueError("pooled validation folds produced no deployable global threshold")
    selected_threshold = max(scored, key=lambda row: (row[1], row[2], row[3], row[4]))[0]

    reports: dict[str, RollingValidationReport] = {}
    for instrument, local in local_reports.items():
        chronological = sorted(trades_by_instrument[instrument], key=lambda trade: trade.signal_time)
        holdout_count = max(1, int(Decimal(len(chronological)) * holdout_fraction))
        development = chronological[:-holdout_count]
        holdout = chronological[-holdout_count:]
        global_folds = tuple(
            replace(
                fold,
                selected_threshold=selected_threshold,
                training=summarize_trades(
                    development[fold.train_start : fold.train_end],
                    minimum_score=selected_threshold,
                ),
                validation=summarize_trades(
                    development[fold.validation_start : fold.validation_end],
                    minimum_score=selected_threshold,
                ),
            )
            for fold in local.folds
        )
        reports[instrument] = RollingValidationReport(
            folds=global_folds,
            selected_threshold=selected_threshold,
            development=summarize_trades(development, minimum_score=selected_threshold),
            holdout=summarize_trades(holdout, minimum_score=selected_threshold),
            holdout_fraction=holdout_fraction,
        )

    total_trades = sum(report.holdout.trades for report in reports.values())
    total_wins = sum(report.holdout.wins for report in reports.values())
    total_r = sum(report.holdout.total_r for report in reports.values())
    return MultiInstrumentValidation(
        by_instrument=reports,
        selected_threshold=selected_threshold,
        holdout_trades=total_trades,
        holdout_win_rate=Decimal("0") if total_trades == 0 else Decimal(total_wins) / Decimal(total_trades),
        holdout_expectancy_r=Decimal("0") if total_trades == 0 else total_r / Decimal(total_trades),
        profitable_instruments=sum(report.holdout.expectancy_r > 0 for report in reports.values()),
    )
