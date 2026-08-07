# Event Catalog and Messaging Contract

## 1. Subject naming

```text
<domain>.<entity-or-purpose>.<event>.v<major>
```

Initial subjects:

| Subject | Producer | Primary consumers |
|---|---|---|
| `market.quote.raw.v1` | market ingestor | raw archive, normalizer |
| `market.quote.normalized.v1` | normalizer | bars, quality, analytics |
| `market.candle.closed.v1` | bar worker | features, replay store |
| `macro.calendar.snapshot.v1` | macro ingestor | event scheduler, archive |
| `macro.release.observed.v1` | macro ingestor | fundamental worker |
| `news.document.observed.v1` | news ingestor | dedupe, NLP |
| `feature.technical.produced.v1` | feature worker | decision worker |
| `feature.fundamental.produced.v1` | fundamental worker | decision worker |
| `strategy.candidate.produced.v1` | decision worker | risk worker, trace store |
| `strategy.candidate.rejected.v1` | decision worker | trace store, analytics |
| `risk.authorization.decided.v1` | risk worker | execution, trace store |
| `execution.order-intent.created.v1` | application | execution worker |
| `execution.broker-event.observed.v1` | broker adapter | lifecycle, reconciliation |
| `portfolio.snapshot.produced.v1` | reconciliation | risk, control API |
| `system.provider-health.changed.v1` | health service | all gates, alerts |
| `audit.decision-trace.finalized.v1` | trace service | analytics, object store |

## 2. Envelope

Every event includes:

```yaml
schema_name: EventEnvelope
schema_version: 1.0.0
event_id: uuidv7
event_type: market.quote.normalized
event_version: 1
occurred_at: provider/event time
observed_at: local receipt time
persisted_at: durable-write time
producer: service role and version
environment: research|shadow|paper|live
correlation_id: workflow ID
causation_id: prior event or command ID
partition_key: deterministic ordering key
idempotency_key: producer-defined duplicate key
source:
  provider: oanda
  channel: pricing-stream
  payload_ref: object-store URI/hash
trace:
  trace_id: W3C trace ID
  span_id: producer span
payload: typed event payload
```

## 3. Ordering

Global ordering is not assumed. Required ordering keys:

- price stream: provider + account/channel + instrument;
- account transaction stream: provider + account;
- decision flow: account + strategy policy + instrument;
- replay: dataset + partition + sequence.

Events with provider sequence IDs store them. If a provider has no sequence, the ingestor assigns a receive sequence while preserving provider time.

## 4. Compatibility

- Additive optional fields are minor versions.
- Semantic changes, field removal, unit changes, or enum reinterpretation require a new major subject.
- Consumers declare supported major versions at startup.
- Unknown fields are preserved at the raw boundary and ignored only by typed consumers.
- A contract registry stores JSON Schema, examples, owner, and compatibility checks.

## 5. Idempotency keys

Examples:

- normalized quote: provider + channel + instrument + provider timestamp + bid + ask;
- calendar snapshot: provider event ID + snapshot observation time;
- news item: canonical source URL hash + publication time + normalized body hash;
- strategy candidate: policy version + instrument + setup anchor event + evaluation time;
- order intent: candidate ID + risk authorization ID + execution plan version.

## 6. Dead-letter handling

A consumer sends an event to a dead-letter subject after bounded retries when the failure is payload-specific. Infrastructure failures do not dead-letter healthy events. Dead-letter records include exception class, safe message, consumer version, attempt count, first/last failure times, and original event reference.

## 7. Replay rules

Replay events retain original `occurred_at` and `observed_at`, but receive a replay-specific envelope containing dataset and run IDs. Replay consumers use the replay clock and cannot connect to live broker adapters.

## 8. Command response pattern

Commands that cross a process boundary use:

```text
command.<domain>.<action>.v1
reply.<domain>.<action>.v1
```

Long-running work returns an accepted workflow ID and emits progress events. Broker order submission is not retried through request/reply alone; the durable order lifecycle controls retries.
