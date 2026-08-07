import pytest

from forex_trader.research.correlation import CorrelationEstimate, correlation_clusters, estimate_pair_correlation, log_returns


def test_log_returns_require_positive_prices() -> None:
    with pytest.raises(ValueError):
        log_returns([1.0, 0.0])


def test_estimate_detects_high_positive_correlation() -> None:
    left = [1.0, 1.01, 1.02, 1.04, 1.03, 1.05]
    right = [2.0, 2.02, 2.04, 2.08, 2.06, 2.10]
    estimate = estimate_pair_correlation("EUR_USD", "GBP_USD", left, right)
    assert estimate.observations == 5
    assert estimate.correlation > 0.99


def test_clusters_use_absolute_correlation() -> None:
    estimates = {
        frozenset({"EUR_USD", "GBP_USD"}): CorrelationEstimate("EUR_USD", "GBP_USD", 100, 0.91),
        frozenset({"USD_JPY", "EUR_USD"}): CorrelationEstimate("USD_JPY", "EUR_USD", 100, -0.35),
    }
    clusters = correlation_clusters(["EUR_USD", "GBP_USD", "USD_JPY"], estimates, threshold=0.8)
    assert frozenset({"EUR_USD", "GBP_USD"}) in clusters
    assert frozenset({"USD_JPY"}) in clusters
