# ADR 0010 — Point-in-Time Feature Snapshots

## Status
Accepted

## Decision
Every decision consumes an immutable feature snapshot with `as_of`, `available_at`, versions, and lineage.

## Rationale
This is required to prevent future leakage and to reproduce decisions.

## Consequences
Late data creates corrections/new versions. Historical decisions are never silently recomputed in place.
