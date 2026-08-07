# 16 — Implementation Status

## Current release

Version 0.3.0 is a functioning OANDA fxTrade Practice / offline-simulation platform. It remains paper-only and contains no live-money endpoint.

```text
completed M5/H1 candles + executable quote
                    +
 point-in-time macro/news/central-bank observations
                    ↓
 technical + fundamental decision engine
                    ↓
 learned session-cost ceiling + explicit abstention
                    ↓
 independent stop, conversion and portfolio risk gate
                    ↓
 protected practice order / shadow trace
                    ↓
 OANDA order reconciliation + transaction ledger
                    ↓
 practice promotion metrics + rolling validation
```

## Implemented runtime components

- Completed-candle M5/H1 technical analysis with EMA structure, ATR, RSI, liquidity sweeps, displacement, quote freshness, spread and executable reward/risk gates.
- Immutable macro observations with exact availability timestamps, source metadata, release forecasts/actuals/previous values, revisions, news and central-bank material.
- Point-in-time fundamental reconstruction that excludes both future observations and future-dated seed state.
- SQLite persistence for decisions, duplicate execution claims, macro history, execution-cost samples, OANDA transactions and durable transaction cursors.
- OANDA Practice account discovery, candles, bounded historical ranges, prices, instrument metadata, positions, currency conversion, protected market orders and trade closing.
- OANDA order reconciliation by client ID with transaction-history fallback. Ambiguous writes are never blindly resubmitted.
- OANDA transaction catch-up and newline-delimited stream consumption with restart-safe cursors and idempotent transaction storage.
- Learned UTC session cost profiles for Asia, London, London/New York overlap, New York and off-hours. Learned limits may tighten but never widen the configured spread ceiling.
- Risk sizing from the lower of balance/NAV with quote-to-account currency conversion, daily loss limits, position limits, unit caps, gross currency exposure and single-currency concentration limits.
- Portfolio risk fails closed when an existing position or currency leg cannot be priced reliably.
- Practice promotion gates based on decision/trade sample sizes, win rate, profit factor, realized P/L, drawdown, broker reject rate, unknown-order rate and median slippage.
- Chronological rolling validation with final untouched holdouts and multi-instrument aggregation.
- CLI, FastAPI, Docker and two-version GitHub Actions verification.

## Operator commands

```bash
forex-trader sync
forex-trader sync --stream --max-events 100
forex-trader promotion
python scripts/import_macro_history.py history.jsonl
python scripts/backtest_oanda.py --instrument EUR_USD --days 90
python scripts/optimize_oanda.py --instrument EUR_USD --days 180
python scripts/validate_oanda.py --instruments EUR_USD,GBP_USD,USD_JPY --days 180
```

Use `--technical-only` on the research scripts only for diagnostic comparison when point-in-time macro history is unavailable. Combined-strategy research defaults to persisted point-in-time observations.

## Network verification boundary

The OANDA credential is read only from `OANDA_API_TOKEN`. It is never persisted by the application. Authenticated Practice probes have been attempted from the implementation environment, but outbound DNS resolution for `api-fxpractice.oanda.com` is blocked before authentication. Contract behavior is covered by deterministic tests; a real authenticated smoke/round-trip must therefore be run from a normal networked host such as the user's Mac.

## Still incomplete

- Automated licensed economic-calendar collection and consensus snapshots.
- Automated licensed news ingestion and official central-bank document collector.
- Futures order-flow proxy ingestion.
- Historical session-specific spread reconstruction from broker tick data rather than user-collected runtime samples.
- Correlation/covariance-aware portfolio limits beyond currency-leg concentration.
- PostgreSQL/TimescaleDB/event-bus deployment for high-volume operation.
- Sufficient untouched historical and live Practice evidence to claim an edge.
- Any live-money execution mode.

No win-rate or profitability claim is supported until the combined system has sufficient point-in-time data and untouched out-of-sample evidence.
