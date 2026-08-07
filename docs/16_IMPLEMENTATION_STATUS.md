# 16 — Implementation Status

## Current release

Version 0.2.0 is a functioning paper-trading platform with an offline deterministic provider and an OANDA fxTrade Practice adapter. It is not a live-money system.

```text
completed M5/H1 candles + executable quote
                    +
       timestamped currency fundamentals
                    ↓
 technical structure and confirmation
                    ↓
     fundamental pair differential
                    ↓
 confirmation, freshness, spread and RR gates
                    ↓
      independent risk authorization
                    ↓
 shadow decision or protected practice order
                    ↓
 persistent decision and execution audit
```

## Implemented components

- Domain models for candles, quotes, instrument specifications, accounts, assessments, candidates, risk authorizations, orders, fills and traces.
- EMA, ATR, RSI, higher-timeframe trend strength, lower-timeframe alignment, liquidity-sweep and displacement analysis.
- Conservative setup requirements for sweep, directional displacement, quote freshness, spread and executable reward/risk.
- Currency-level fundamental state updated by economic releases and news observations.
- Fundamental freshness reduction and explicit conflict rejection.
- Position sizing from the lower of balance and NAV.
- Score-scaled risk budgets, daily realized-loss limits, open-position limits and maximum units.
- Protection-level validation for long and short orders.
- Persistent duplicate signal-candle claims, with release only after a definite broker rejection.
- Ambiguous market-order transport outcomes are recorded as `UNKNOWN` and retain the execution claim.
- Same-instrument position stacking prevention.
- Deterministic synthetic market data and simulated paper fills.
- OANDA Practice account discovery, summary, tradeable-instrument metadata, candles, quotes, open positions, order placement and trade closure.
- OANDA display-precision, pip-location, unit-precision and minimum/maximum-order enforcement.
- OANDA bounded retries for read-only requests and credential-safe exceptions.
- Market-order requests are never blindly retried after an ambiguous transport or 5xx outcome.
- OANDA daily realized P/L reconstruction from UTC-day transaction pages.
- Read-only broker probe and self-closing minimum-size round-trip test.
- SQLite decision traces and atomic execution claims.
- FastAPI control plane and Typer CLI.
- Conservative spread-aware candle barrier backtesting, completion-time controls, performance summaries and chronological threshold optimization.
- Docker image, Compose configuration and GitHub Actions.

## Validation state

The local acceptance run for version 0.2.0 includes:

- all tests passing;
- branch-aware coverage above the repository minimum;
- Python bytecode compilation;
- dependency consistency checks;
- offline shadow evaluation;
- offline protected paper execution;
- duplicate-order and open-position regression tests;
- OANDA contract tests through mocked official response shapes.

Authenticated OANDA Practice network verification must be performed in an environment with external network access. Tokens are never committed or embedded in CI configuration.

## Deliberately incomplete

The following remain future phases:

- automatic licensed economic-calendar ingestion;
- historical point-in-time economic consensus and revisions;
- licensed real-time news and central-bank document extraction;
- futures order-flow proxy ingestion;
- complete OANDA transaction-stream reconciliation and restart state recovery;
- conversion-aware risk sizing for non-USD crosses;
- portfolio-level correlated currency exposure;
- PostgreSQL/TimescaleDB and event-bus deployment;
- longer historical datasets and untouched out-of-sample validation;
- any live-money endpoint, credential or activation path.

No win-rate or profit claim is supported until the missing point-in-time data and out-of-sample evidence exist.
