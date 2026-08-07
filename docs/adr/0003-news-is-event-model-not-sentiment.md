# ADR 0003 — News as an Event Model, Not Generic Sentiment

## Status

Accepted for framework.

## Decision

News intelligence must classify event type, affected currencies, novelty, reliability, horizon, and directional impact relative to expectations. Generic positive/negative sentiment cannot directly authorize trades.

## Rationale

FX impact depends on consensus, policy regime, base/quote relationship, positioning, and what is already priced. Generic sentiment loses these relationships.

## Consequences

- More complex schemas and training data.
- Greater abstention.
- Better explainability.
- Scheduled releases use deterministic numerical models before language-model interpretation.
