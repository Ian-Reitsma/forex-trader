# 16 — Implementation Status

## Implemented vertical slice

The repository now contains a runnable Python platform rather than specifications only. The implemented path is:

```text
M5/H1 candles + executable quote
        +
versioned currency fundamental state
        ↓
technical assessment
        ↓
fundamental pair assessment
        ↓
deterministic signal fusion
        ↓
independent risk authorization
        ↓
shadow decision or paper order
        ↓
SQLite decision trace
```

The default provider is deterministic simulation. OANDA fxTrade Practice is the initial external paper broker and market-data adapter.

## Implemented components

- Pure domain models for candles, quotes, accounts, technical/fundamental assessments, candidates, risk authorizations, orders, and traces.
- EMA, RSI, ATR, multi-timeframe trend, liquidity-sweep, displacement, spread, stop, and take-profit calculations.
- Currency-level fundamental state updated from economic releases and news text.
- Regime-neutral deterministic signal-fusion policy with explicit abstention reasons.
- Stop-distance position sizing for USD accounts and USD pairs.
- Independent limits for per-trade risk, daily realized loss, open positions, and maximum units.
- Deterministic synthetic market-data provider.
- Simulated paper broker.
- OANDA Practice REST adapter for account discovery, account summary, candles, quotes, and protected market orders.
- SQLite decision-trace persistence.
- FastAPI control plane.
- Typer CLI for configuration checks, one-shot evaluation, finite or continuous cycles, and API serving.
- Docker image and compose file.
- GitHub Actions tests on Python 3.11 and 3.13.

## Deliberately not represented as complete

The implementation is a functioning paper-trading MVP, not a production-ready autonomous trading system. The following specifications remain future phases:

- licensed real-time economic-calendar and news-provider ingestion;
- central-bank document extraction and LLM-assisted structured analysis;
- futures order-flow proxy ingestion;
- PostgreSQL/TimescaleDB, NATS JetStream, and object-store deployment;
- broker transaction-stream reconciliation after disconnects;
- non-USD cross conversion for risk sizing;
- portfolio-level correlated exposure and multi-account allocation;
- walk-forward historical replay using licensed point-in-time datasets;
- multi-party live authorization and any live credential path.

No live endpoint is configured or permitted by the current implementation.
