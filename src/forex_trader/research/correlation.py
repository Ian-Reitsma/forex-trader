from __future__ import annotations

from dataclasses import dataclass
from math import log, sqrt
from statistics import fmean
from typing import Iterable, Mapping, Sequence


@dataclass(frozen=True, slots=True)
class CorrelationEstimate:
    left: str
    right: str
    observations: int
    correlation: float


def log_returns(prices: Sequence[float]) -> list[float]:
    if len(prices) < 2:
        return []
    if any(price <= 0 for price in prices):
        raise ValueError("prices must be positive")
    return [log(prices[i] / prices[i - 1]) for i in range(1, len(prices))]


def pearson(left: Sequence[float], right: Sequence[float]) -> float:
    if len(left) != len(right):
        raise ValueError("series must be aligned")
    if len(left) < 2:
        raise ValueError("at least two observations are required")
    ml, mr = fmean(left), fmean(right)
    numerator = sum((a - ml) * (b - mr) for a, b in zip(left, right, strict=True))
    dl = sum((a - ml) ** 2 for a in left)
    dr = sum((b - mr) ** 2 for b in right)
    denominator = sqrt(dl * dr)
    return 0.0 if denominator == 0 else max(-1.0, min(1.0, numerator / denominator))


def estimate_pair_correlation(
    left: str,
    right: str,
    left_prices: Sequence[float],
    right_prices: Sequence[float],
) -> CorrelationEstimate:
    if len(left_prices) != len(right_prices):
        raise ValueError("price series must be aligned before correlation estimation")
    lret, rret = log_returns(left_prices), log_returns(right_prices)
    if len(lret) < 2:
        raise ValueError("insufficient history for correlation estimation")
    return CorrelationEstimate(left, right, len(lret), pearson(lret, rret))


def correlation_clusters(
    instruments: Iterable[str],
    estimates: Mapping[frozenset[str], CorrelationEstimate],
    *,
    threshold: float = 0.80,
) -> tuple[frozenset[str], ...]:
    if not 0 <= threshold <= 1:
        raise ValueError("threshold must be between 0 and 1")
    nodes = set(instruments)
    adjacency = {node: set() for node in nodes}
    for key, estimate in estimates.items():
        if len(key) != 2 or not key <= nodes:
            continue
        if abs(estimate.correlation) >= threshold:
            a, b = tuple(key)
            adjacency[a].add(b)
            adjacency[b].add(a)
    clusters: list[frozenset[str]] = []
    unseen = set(nodes)
    while unseen:
        root = unseen.pop()
        stack = [root]
        component = {root}
        while stack:
            current = stack.pop()
            for neighbour in adjacency[current]:
                if neighbour in unseen:
                    unseen.remove(neighbour)
                    component.add(neighbour)
                    stack.append(neighbour)
        clusters.append(frozenset(component))
    return tuple(sorted(clusters, key=lambda group: tuple(sorted(group))))
