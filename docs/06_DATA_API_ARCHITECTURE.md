# 06 — Data and API Architecture

## 1. Architectural objective

Create a provider-independent data plane that preserves raw source data, normalizes it into canonical events, supports real-time decisions, and can replay the exact information available at any historical instant.

## 2. Provider roles

### Execution broker

Source of executable bid/ask, account state, orders, fills, margin, and positions. Initial recommended adapter: OANDA v20 practice/live for spot FX. Alternative: Interactive Brokers for broader asset coverage and paper/live APIs.

### Institutional order-flow provider

Preferred source for centralized volume, delta, depth, and volume profile. Target hierarchy:

1. CME FX futures direct or licensed vendor;
2. CME/EBS products or consolidated FX reference;
3. institutional vendors such as LSEG, dxFeed, CQG, Rithmic, or equivalent;
4. broker-local activity features as low-confidence fallback.

### Economic calendar and macro data

Trading Economics or comparable normalized calendar with streaming actuals, consensus, previous, revisions, importance, and source links. Direct official-source connectors remain the authority layer.

### News

Premium target: licensed low-latency machine-readable news. Cost-conscious research: normalized economic news plus direct official communications. General aggregators are supplemental.

### Cross-asset data

Government yields, rate futures, index futures, commodities, volatility, and dollar indexes from licensed providers.

## 3. Ingestion pattern

Each connector runs independently and publishes source events.

```text
CONNECT → AUTHENTICATE → SNAPSHOT → STREAM → HEARTBEAT
        → RECONNECT → GAP_DETECT → BACKFILL → RESUME
```

The connector must expose health, lag, rate-limit state, reconnect count, last event time, and sequence gaps.

## 4. Canonical event envelope

```text
event_id
event_type
schema_version
source
source_event_id
instrument_or_entity
source_timestamp
received_timestamp
normalized_timestamp
sequence
payload_hash
quality_flags
raw_payload_pointer
correlation_id
```

The raw payload is immutable. Normalized events can be reprocessed with new parsers.

## 5. Time discipline

- UTC internally.
- Nanosecond or microsecond precision where sources support it.
- Monotonic process clocks for latency.
- NTP/PTP monitoring in production.
- Separate source time, receive time, and processing time.
- Daylight-saving-aware market calendars.
- Explicit handling for ambiguous or missing timestamps.

## 6. Storage layers

### Raw object store

Unmodified provider payloads, compressed and partitioned by source/date/type.

### Immutable event log

Ordered canonical events for replay and audit.

### Time-series store

Quotes, trades, bars, spreads, depth summaries, yields, and derived metrics.

### Relational metadata store

Instruments, provider mappings, calendars, models, configurations, decisions, orders, and approvals.

### Feature store

Point-in-time features with lineage, freshness, and version.

### Analytics warehouse

Backtests, attribution, experiments, reports, and aggregate metrics.

## 7. Event bus

A durable streaming platform such as Kafka, Redpanda, or NATS JetStream can be evaluated during implementation.

Candidate topics:

- `market.quote.raw`
- `market.trade.raw`
- `market.depth.raw`
- `macro.calendar.scheduled`
- `macro.release.actual`
- `news.story`
- `central_bank.communication`
- `feature.technical`
- `feature.fundamental`
- `feature.flow`
- `strategy.candidate`
- `risk.decision`
- `execution.order_intent`
- `execution.order_event`
- `portfolio.snapshot`
- `system.health`

Exact technology is deferred; semantic boundaries are not.

## 8. Data quality service

Checks:

- freshness;
- continuity;
- crossed or locked quotes;
- impossible prices;
- spread outliers;
- duplicate events;
- sequence gaps;
- source disagreement;
- stale account state;
- timestamp reversals;
- contract-roll mapping;
- calendar event mismatch;
- consensus changes after release;
- revision contamination.

Quality results are published as events and can hard-stop trading.

## 9. Point-in-time guarantees

Historical simulations must only access data known at that time.

Specific controls:

- store each consensus snapshot over time;
- preserve original previous value and later revision;
- timestamp news receipt, not merely publication;
- record provider delay;
- use historical instrument mappings and contract rolls;
- do not recompute historical bars with future corrections unless running a separate corrected-data study;
- version all reference data.

## 10. API adapter contract

Every provider adapter implements conceptual capabilities:

```text
connect()
health()
snapshot()
stream()
backfill()
normalize()
rate_limit_state()
close()
```

Execution adapters additionally implement:

```text
get_account()
get_positions()
get_orders()
submit_order(intent)
modify_order()
cancel_order()
close_position()
stream_transactions()
reconcile()
```

The framework uses capability detection because not every broker supports the same order types or guarantees.

## 11. Provider redundancy

Redundancy is role-specific:

- two executable quote sources for sanity checking;
- primary and secondary calendar feeds;
- direct official source as authority for major releases;
- broker account stream plus periodic REST reconciliation;
- fallback order-flow source that can disable flow-required strategies rather than fabricate data.

Failover should degrade functionality conservatively. A missing flow feed may disable sweep strategies; it should not silently replace delta with RSI.

## 12. Data contracts before implementation

Before code, define schemas for:

- quote;
- trade;
- depth snapshot/delta;
- bar;
- economic event;
- news event;
- central-bank document;
- currency fundamental vector;
- zone;
- liquidity pool;
- technical setup;
- trade candidate;
- risk decision;
- order intent;
- broker order event;
- fill;
- position;
- decision trace;
- system health.

These schemas become the integration boundary and should be reviewed before choosing databases.

## 13. Latency classes

Not all data requires the same path.

- Class A: broker quotes, fills, protective orders.
- Class B: scheduled release actuals and critical news.
- Class C: futures flow and technical features.
- Class D: macro state, research analytics, reports.

Architecture and cost should prioritize Class A and B. A large language model must not add unnecessary delay to protective execution.

## 14. Cost-aware provider plan

### Research baseline

- OANDA practice for executable prices and order lifecycle;
- Trading Economics for calendar and normalized macro events;
- official central-bank/statistics sources;
- affordable futures data vendor;
- local historical store.

### Production target

- redundant broker/reference quote source;
- licensed CME futures depth;
- institutional low-latency news;
- production-grade streaming infrastructure;
- colocated or region-optimized deployment if latency evidence justifies it.

Provider upgrades occur only when measured edge or reliability justifies cost.
