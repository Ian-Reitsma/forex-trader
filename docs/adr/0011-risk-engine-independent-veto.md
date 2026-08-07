# ADR 0011 — Independent Risk Veto

## Status
Accepted

## Decision
Risk authorization is produced by a separate boundary and is mandatory, scoped, expiring, and verified by execution.

## Rationale
Strategy confidence cannot be allowed to override portfolio, loss, margin, data, or operational safety.

## Consequences
Risk unavailability denies new orders. Material execution changes require reauthorization.
