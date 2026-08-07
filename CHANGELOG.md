# Changelog

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
