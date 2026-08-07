# Changelog

## 0.3.0 — 2026-08-06

### Added

- Immutable point-in-time macro/news/central-bank history with JSONL import and API ingestion.
- OANDA client-ID order reconciliation, transaction-since-ID catch-up and streaming synchronization with a durable SQLite cursor.
- Session-specific spread/slippage sampling that can only tighten the configured hard spread ceiling.
- Cross-currency risk conversion, portfolio currency-leg exposure limits and fail-closed behavior when existing exposure cannot be priced.
- Rolling train/validation windows, untouched holdouts and multi-instrument validation tools.
- Practice promotion gates based on sample size, win rate, profit factor, realized P/L, drawdown, reject/unknown rates and slippage.
- CLI commands for broker synchronization and promotion status.

### Changed

- Historical replay can consume point-in-time fundamentals rather than a current-state snapshot.
- OANDA Practice client is independently locked to practice REST and stream hosts and follows safe redirects.
- Same-instrument position detection reuses the broker position snapshot instead of issuing a duplicate position request.
- Existing portfolio exposure must be fully priceable before new risk can be authorized.

### Verification

- All external OANDA probes continue to use environment-only credentials.
- In this execution environment the supplied Practice credential reaches the real client code path but DNS resolution for `api-fxpractice.oanda.com` is blocked before authentication.
- No credential is written to Git, CI, documentation or logs.

## 0.2.0 — 2026-08-06

### Added

- OANDA Practice instrument metadata, pricing, account, protected-order and trade-close support.
- Read-only OANDA probe and explicitly gated minimum-size round-trip verification script.
- Conservative technical-only walk-forward replay and chronological threshold calibration tools.
- Persistent execution claims that prevent duplicate submissions across process restarts.
- Same-instrument position blocking and OANDA daily realized-P/L reconstruction.
- Tests for broker formatting, retries, transaction paging, duplicate protection and backtesting.

### Changed

- Raised default setup selectivity with liquidity-sweep, displacement, quote-freshness, spread and executable reward/risk gates.
- Risk sizing now uses the lower of balance and NAV and scales exposure by setup score.
- OANDA prices and units now use broker-provided instrument precision and trade-size constraints.
- Market-order transport ambiguity is preserved as `UNKNOWN`; the adapter does not blindly retry a potentially accepted order.
- Historical replay now waits for candle completion and applies spread to both entry and exit barriers.

### Safety

- The application remains OANDA Practice-only and rejects all other OANDA REST hosts.
- Tokens remain environment-only and are excluded from representations, output and repository files.
- No live-money execution path exists.
