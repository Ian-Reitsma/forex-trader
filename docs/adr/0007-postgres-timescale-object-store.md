# ADR 0007 — PostgreSQL/TimescaleDB plus Object Storage

## Status
Accepted

## Decision
Use PostgreSQL for operational state, TimescaleDB for time series when available, and S3-compatible object storage for raw immutable payloads and replay bundles.

## Rationale
This minimizes database sprawl while preserving exact operational transactions and inexpensive raw retention.

## Consequences
Large analytical workloads may later replicate into a warehouse. Object references and checksums are first-class lineage fields.
