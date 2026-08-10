from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from math import log, sqrt
from statistics import fmean
from typing import Callable, Iterable

from forex_trader.domain.enums import Direction
from forex_trader.domain.models import Candle, TradeCandidate
from forex_trader.domain.portfolio import OpenPosition


@dataclass(frozen=True, slots=True)
class CorrelationPairRisk:
    existing_instrument: str
    observations: int
    raw_correlation: float
    signed_pnl_correlation: float


@dataclass(frozen=True, slots=True)
class CorrelationRiskDecision:
    blocked: bool
    reason: str | None
    pairs: tuple[CorrelationPairRisk, ...]
    max_signed_correlation: float | None


class CorrelationRiskGuard:
    """Veto duplicated P/L risk using recent aligned higher-timeframe returns.

    Raw price correlation is converted into *signed P/L correlation* by accounting for
    the proposed and existing position directions. Thus two positively correlated pairs
    held in opposite directions are not treated the same as two same-direction bets.
    This is a veto only; low correlation never increases position size.
    """

    def __init__(
        self,
        candle_loader: Callable[[str, str, int], list[Candle]],
        *,
        semantic_granularity: str = "H1",
        lookback: int = 81,
        minimum_observations: int = 40,
        maximum_signed_correlation: float = 0.85,
        fail_closed: bool = True,
    ) -> None:
        if lookback < minimum_observations + 1:
            raise ValueError("correlation lookback must exceed minimum observations")
        if minimum_observations < 10:
            raise ValueError("minimum correlation observations must be at least 10")
        if not 0 < maximum_signed_correlation <= 1:
            raise ValueError("maximum_signed_correlation must be in (0, 1]")
        self.candle_loader = candle_loader
        self.semantic_granularity = semantic_granularity
        self.lookback = lookback
        self.minimum_observations = minimum_observations
        self.maximum_signed_correlation = maximum_signed_correlation
        self.fail_closed = fail_closed

    def evaluate(
        self,
        candidate: TradeCandidate,
        positions: Iterable[OpenPosition],
    ) -> CorrelationRiskDecision:
        existing = [position for position in positions if position.net_units != 0]
        if not existing:
            return CorrelationRiskDecision(False, None, (), None)
        if candidate.direction not in {Direction.LONG, Direction.SHORT}:
            return CorrelationRiskDecision(True, "flat candidate cannot pass correlation risk", (), None)
        try:
            candidate_prices = self._prices(candidate.instrument)
        except Exception as exc:
            return self._data_failure(candidate.instrument, exc)

        candidate_sign = 1.0 if candidate.direction is Direction.LONG else -1.0
        pairs: list[CorrelationPairRisk] = []
        for position in existing:
            try:
                existing_prices = self._prices(position.instrument)
                common = sorted(set(candidate_prices) & set(existing_prices))
                if len(common) < self.minimum_observations + 1:
                    raise ValueError(
                        f"only {len(common) - 1} aligned returns; need {self.minimum_observations}"
                    )
                common = common[-(self.lookback):]
                left = [candidate_prices[stamp] for stamp in common]
                right = [existing_prices[stamp] for stamp in common]
                left_returns = _log_returns(left)
                right_returns = _log_returns(right)
                if len(left_returns) < self.minimum_observations:
                    raise ValueError("insufficient aligned return history")
                raw = _pearson(left_returns, right_returns)
                existing_sign = 1.0 if position.net_units > 0 else -1.0
                signed = raw * candidate_sign * existing_sign
                pairs.append(
                    CorrelationPairRisk(
                        existing_instrument=position.instrument,
                        observations=len(left_returns),
                        raw_correlation=raw,
                        signed_pnl_correlation=signed,
                    )
                )
            except Exception as exc:
                if self.fail_closed:
                    return CorrelationRiskDecision(
                        True,
                        f"correlation risk could not price {position.instrument}: {type(exc).__name__}: {exc}",
                        tuple(pairs),
                        max((item.signed_pnl_correlation for item in pairs), default=None),
                    )

        max_signed = max((item.signed_pnl_correlation for item in pairs), default=None)
        if max_signed is not None and max_signed >= self.maximum_signed_correlation:
            worst = max(pairs, key=lambda item: item.signed_pnl_correlation)
            return CorrelationRiskDecision(
                True,
                (
                    f"signed P/L correlation {worst.signed_pnl_correlation:.3f} with "
                    f"{worst.existing_instrument} exceeds {self.maximum_signed_correlation:.3f}"
                ),
                tuple(pairs),
                max_signed,
            )
        return CorrelationRiskDecision(False, None, tuple(pairs), max_signed)

    def _prices(self, instrument: str) -> dict[datetime, float]:
        candles = [
            candle
            for candle in self.candle_loader(
                instrument.upper(), self.semantic_granularity, self.lookback
            )
            if candle.complete
        ]
        if len(candles) < self.minimum_observations + 1:
            raise ValueError(
                f"{instrument} has {len(candles)} completed candles; need {self.minimum_observations + 1}"
            )
        return {candle.time: float(candle.close) for candle in candles}

    def _data_failure(self, instrument: str, exc: Exception) -> CorrelationRiskDecision:
        if not self.fail_closed:
            return CorrelationRiskDecision(False, None, (), None)
        return CorrelationRiskDecision(
            True,
            f"correlation risk could not price {instrument}: {type(exc).__name__}: {exc}",
            (),
            None,
        )


def _log_returns(prices: list[float]) -> list[float]:
    if any(price <= 0 for price in prices):
        raise ValueError("correlation prices must be positive")
    return [log(current / previous) for previous, current in zip(prices[:-1], prices[1:], strict=True)]


def _pearson(left: list[float], right: list[float]) -> float:
    if len(left) != len(right) or len(left) < 2:
        raise ValueError("correlation return series must be aligned")
    mean_left = fmean(left)
    mean_right = fmean(right)
    numerator = sum(
        (a - mean_left) * (b - mean_right)
        for a, b in zip(left, right, strict=True)
    )
    left_var = sum((value - mean_left) ** 2 for value in left)
    right_var = sum((value - mean_right) ** 2 for value in right)
    denominator = sqrt(left_var * right_var)
    if denominator == 0:
        return 0.0
    return max(-1.0, min(1.0, numerator / denominator))
