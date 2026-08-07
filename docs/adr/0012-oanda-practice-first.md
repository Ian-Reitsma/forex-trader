# ADR 0012 — OANDA Practice First

## Status
Proposed

## Decision
Implement OANDA v20 practice pricing, order, transaction, account, and reconciliation adapters first.

## Rationale
It supplies an accessible practice environment and a coherent API surface for the first end-to-end broker lifecycle.

## Consequences
The domain remains broker-agnostic. The documented pricing stream is throttled and is not treated as full-tick institutional order flow.
