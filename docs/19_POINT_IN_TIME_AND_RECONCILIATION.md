# 19 — Point-in-Time State, Reconciliation and Promotion

## Macro event store

Every release, news item or central-bank observation is immutable. Corrections/revisions are new observations linked with `revision_of`; history is never overwritten. `available_at` represents when the system could first have known the observation, not the economic period to which the value refers.

Example JSONL release:

```json
{"kind":"release","currency":"USD","available_at":"2026-07-03T12:30:00+00:00","source":"BLS","category":"labor","actual":"147","forecast":"110","previous":"144","higher_is_positive":true,"importance":"1"}
```

Example news/central-bank observation:

```json
{"kind":"central_bank","currency":"EUR","available_at":"2026-07-24T12:15:00+00:00","source":"ECB","headline":"Policy decision","body":"...","source_weight":"1"}
```

## Unknown-order recovery

An uncertain market-order HTTP outcome is `UNKNOWN`, never an excuse to submit the same order again. Recovery order:

1. query OANDA by the persisted client order ID;
2. fetch the exact fill transaction when available;
3. if the order lookup is absent, scan recent OANDA transactions for matching client extensions;
4. classify the original request as filled, created, rejected or still unknown;
5. retain the execution claim until the outcome is definitely rejected.

## Transaction synchronization

`forex-trader sync` catches up from the durable OANDA transaction cursor. `forex-trader sync --stream` first catches up and then consumes OANDA's transaction stream. Stored transaction IDs are idempotent, so restarts cannot duplicate realized P/L records.

## Portfolio risk

Every open position is decomposed into base and quote currency legs and converted into account-currency exposure. New orders are rejected when gross or single-currency concentration would exceed configured limits. Missing conversion/mark data fails closed.

## Promotion state

Promotion is based on accumulated Practice evidence, not merely a backtest. The default gate requires a meaningful number of decisions, trade candidates and closed trades, positive net realized P/L, minimum win rate and profit factor, bounded drawdown, low reject/unknown rates and controlled slippage.
