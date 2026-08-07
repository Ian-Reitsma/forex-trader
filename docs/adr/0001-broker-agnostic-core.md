# ADR 0001 — Broker-Agnostic Domain Core

## Status

Accepted for framework.

## Decision

All strategy, risk, portfolio, and domain schemas remain independent of broker SDKs. Broker-specific objects are confined to adapters.

## Rationale

Broker APIs, order types, account models, and eligibility can change. The core system must support OANDA first without making migration or multi-broker comparison prohibitively expensive.

## Consequences

- More mapping work at the adapter boundary.
- Stronger testability.
- Paper and simulation adapters can share the same intent contract.
- Strategy code cannot call a broker client directly.
