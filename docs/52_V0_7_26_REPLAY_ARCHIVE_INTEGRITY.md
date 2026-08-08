# 52 — v0.7.26 Historical Replay Archive Integrity

## Purpose

v0.7.26 implements the software contract required to consume future historical executable and point-in-time multi-source archives without silently weakening the research standard. The repository still does not bundle licensed historical bid/ask/tick, macro-consensus, news, cross-asset, or centralized-flow archives. This release defines how such data must be packaged, verified, ordered, and queried before it can enter replay research.

The replay subsystem is research-only. It does not authorize broker risk, change strategy authority, or submit orders.

## Existing scheduler retained

The repository already contained `EventReplayScheduler`, which orders `ReplayEvent` instances by:

```text
available_at -> provider_sequence -> event_id
```

v0.7.26 does not create a competing scheduler. It adds an integrity-bound archive layer around that existing deterministic ordering contract.

## Archive manifest

Every replay dataset begins with a JSON manifest containing:

- schema version;
- immutable dataset ID;
- creation timestamp;
- replay availability period;
- one or more relative source-file paths;
- SHA-256 digest for every source file;
- event types declared by each source file;
- event types that the complete dataset is required to contain;
- optional explicit FX instrument universe.

Absolute source paths are rejected. Paths that resolve outside the manifest directory are rejected. This prevents a manifest from quietly reading arbitrary local files.

The manifest itself has a deterministic canonical hash. The loaded archive has a separate aggregate archive hash derived from the manifest hash plus verified source-file checksums.

## Per-event integrity

Every JSONL event record includes:

```text
event_id
event_type
occurred_at
available_at
provider
channel
provider_sequence
payload
payload_sha256
```

The payload hash is recomputed from canonical sorted JSON before the record is accepted. Changing a source file and updating only the file checksum is therefore insufficient to bypass event-level integrity; the affected event hash must also match the payload actually stored.

The loader rejects:

- duplicate event IDs across all source files;
- duplicate `(provider, channel, provider_sequence)` identities;
- undeclared event types;
- events outside the manifest availability period;
- missing required event types;
- malformed/naive timestamps;
- invalid JSONL rows;
- checksum drift;
- payload-hash drift.

## Historical executable quote contract

`executable_quote` records carry actual archived bid and ask, not a candle-derived midpoint approximation. Each quote has:

- FX instrument;
- bid;
- ask;
- occurrence time;
- point-in-time availability time;
- provider/channel/sequence identity;
- tradeable state.

The quote contract rejects nonpositive pricing and crossed quotes where `ask < bid`.

`PointInTimeExecutableQuoteBook.quote_at(...)` uses only records whose `available_at` is less than or equal to the research cutoff. It never interpolates between quotes and never reaches forward to a future observation. If there is no qualifying quote, or the latest quote is older than the caller's explicit maximum-age bound, lookup fails closed.

Nontradeable quotes are excluded by default. Research can inspect them only by explicitly setting `require_tradeable=False`.

## Multi-source replay

`ReplayArchiveBundle` can combine executable quotes with point-in-time event types such as:

- economic-calendar consensus snapshots;
- economic actuals and revisions;
- news receipt events;
- official central-bank documents;
- cross-asset repricing observations;
- centralized futures/order-flow observations;
- broker/execution evidence.

The loader is event-type-neutral except for the stricter executable-quote validation. Source-specific semantics remain the responsibility of the corresponding deterministic research/ingestion adapters.

Once verified, the bundle exposes the existing `EventReplayScheduler`, preserving the repository's established order:

```text
available_at -> provider_sequence -> event_id
```

This allows simultaneous macro/news/market events to be replayed consistently without relying on file order.

## Operator validation

Use:

```bash
python scripts/validate_replay_archive.py replay/manifest.json
```

or persist the report:

```bash
python scripts/validate_replay_archive.py replay/manifest.json \
  --output replay-validation.json
```

A successful report includes dataset identity, manifest/archive hashes, record counts, event-type counts, provider counts, executable-quote instrument counts, and the required event types.

Validation proves that the archive conforms to the software/integrity contract. It does not prove that a vendor's historical data is economically correct, complete at the market-microstructure level, licensed for the intended use, or sufficient to demonstrate an edge.

## What this closes

v0.7.26 closes the missing consumer/integrity side of the audit's historical replay requirement:

- deterministic multi-source event ordering exists;
- source files are checksum-bound;
- individual payloads are hash-bound;
- source coverage can be required explicitly;
- historical executable bid/ask has a typed contract;
- quote staleness is explicit;
- future-data reach-forward is prohibited;
- quote interpolation is prohibited;
- archive tampering and identity collisions fail closed.

## What remains external

The actual historical data remains an external evidence gap. A serious institutional-grade replay still requires acquisition of:

- historical executable bid/ask/tick archives over the required periods;
- true point-in-time economic consensus and release/revision history;
- point-in-time real-time news receipt archives;
- rates/rate-futures, volatility, equity, commodity, broad-dollar, and carry history;
- CME/equivalent centralized FX futures/order-flow history with correct contract roll/orientation mapping;
- broker metadata changes and trading-session/holiday context where relevant.

The archive should then be validated, frozen, versioned, replayed chronologically, and used within the existing calibration/validation/holdout and after-cost research discipline.

## Authority boundary

No replay result automatically promotes a strategy. Historical evidence is only one stage of the promotion path. Strategy authority remains separately controlled by `config/system-policy-v0.7.json`, risk remains independent, and authenticated prospective OANDA Practice evidence remains required.

## Closed-market boundary

This software work is being completed on Saturday, August 8, 2026 while the FX market is closed. That makes deterministic archive/research work appropriate; it does not make stale weekend broker conditions representative execution evidence.
