# Data Pipelines

## 1. Ingestion stages

Every provider pipeline implements:

```text
CONNECT -> AUTHENTICATE -> SUBSCRIBE -> RECEIVE -> ARCHIVE RAW
-> VALIDATE -> NORMALIZE -> QUALITY SCORE -> PUBLISH -> CHECKPOINT
```

Raw archival occurs before semantic normalization when practical. A malformed payload is still retained with a parse-failure record.

## 2. Market-price pipeline

### Inputs

- executable broker bid/ask stream;
- optional independent spot reference;
- CME futures or FX Tape+ analytical stream;
- historical backfill endpoint.

### Output rules

- preserve bid and ask, not only midpoint;
- preserve liquidity levels when provided;
- record tradeable status;
- record provider and local timestamps;
- detect duplicates, backwards timestamps, crossed quotes, zero/negative prices, and unreasonable jumps;
- never interpolate quotes for execution decisions;
- gaps may be marked for analytics, not hidden.

### Candle building

Bars are derived from the exact configured input: bid, ask, midpoint, or trade. Each bar stores its basis. A candle becomes visible to strategies only after the close boundary plus a watermark delay. Late events either produce a correction version or are excluded according to the declared policy; they never silently rewrite a historical bar used by a prior decision.

## 3. Economic-calendar pipeline

The system stores multiple snapshots of the same scheduled event because consensus, previous values, importance, and release time can change.

Required sequence:

1. load future calendar;
2. reconcile provider IDs to a canonical event identity;
3. snapshot at configured intervals;
4. freeze the last pre-release snapshot;
5. observe actual release and provider receipt time;
6. observe revisions separately;
7. fetch official release when available;
8. calculate provider latency and source agreement;
9. publish normalized release events.

Do not overwrite the pre-release `previous` value with a revised value learned after the release.

## 4. News and official-document pipeline

Stages:

- fetch metadata and body;
- retain original bytes and terms-compliant reference;
- canonicalize source and publication time;
- language detection;
- near-duplicate clustering;
- entity and currency linking;
- event classification;
- claim extraction with evidence spans;
- contradiction and ambiguity detection;
- model calibration and abstention;
- publish structured assessment.

Wire copies are clustered so one story does not become many independent votes.

## 5. Futures-to-spot mapping

The mapping table includes futures contract, spot pair, quote orientation, multiplier, active contract window, roll rule, session, and confidence. Inverse orientation is handled explicitly. Features from the roll window carry a quality penalty or are disabled.

## 6. Watermarks

Each stream maintains:

- maximum observed event time;
- allowed lateness;
- watermark;
- last durable checkpoint;
- gap state.

A multi-source feature snapshot uses the minimum safe watermark required by its policy. Faster streams do not pull slower streams into the future.

## 7. Backfill

Backfill jobs write through the same normalization contracts but use a backfill source mode. They must not publish live decision triggers. A dataset manifest records provider query, time range, checksum, retrieval time, license scope, and transformation version.

## 8. Data quality scores

Quality dimensions are separate:

- freshness;
- completeness;
- sequence integrity;
- cross-source agreement;
- timestamp confidence;
- schema validity;
- provider health;
- license/usage eligibility.

A single blended score may be shown for dashboards, but trading gates inspect the dimensions they require.

## 9. Retention

- raw licensed payloads: per license and research requirement;
- normalized ticks: compressed, partitioned, and retained long enough for execution research;
- candles/features: long-term with version lineage;
- decision, risk, order, and audit events: retained for the life of the system plus legal requirements;
- secrets: never retained in payload stores.
