# Storage and Database Schema

## 1. Storage ownership

PostgreSQL is authoritative for operational state and metadata. TimescaleDB hypertables are recommended for high-volume time series. The object store is authoritative for immutable raw payloads and replay bundles. The event bus is transport, not the only system of record.

## 2. Core relational tables

### `event_inbox`

Consumer idempotency and processing status.

- `consumer_name`
- `event_id`
- `event_type`
- `received_at`
- `processed_at`
- `status`
- `error_code`
- primary key: `(consumer_name, event_id)`

### `event_outbox`

Transactional publication after state changes.

- `outbox_id`
- `aggregate_type`
- `aggregate_id`
- `event_type`
- `payload_json`
- `created_at`
- `published_at`
- `attempt_count`

### `raw_payloads`

- `payload_id`
- `provider`
- `channel`
- `observed_at`
- `sha256`
- `object_uri`
- `content_type`
- `compression`
- `license_class`
- unique: `(provider, channel, sha256)` where permitted

### `instrument_mappings`

Canonical instrument to provider symbols, precision, pip location, minimum size, and active dates.

### `quote_ticks`

Hypertable partitioned by time and instrument.

- `instrument_id`
- `event_time`
- `observed_at`
- `bid`
- `ask`
- `mid`
- `tradeable`
- `provider`
- `source_event_id`
- `quality_state`

Indexes: `(instrument_id, event_time desc)` and `(source_event_id)`.

### `candles`

- `instrument_id`
- `timeframe`
- `price_basis`
- `open_time`
- `close_time`
- OHLC and optional volume fields
- `is_final`
- `revision`
- `feature_input_cutoff`
- unique: `(instrument_id, timeframe, price_basis, open_time, revision)`

### `economic_events`

Canonical identity and stable metadata.

### `economic_event_snapshots`

Point-in-time forecast, previous, release schedule, importance, provider, and observation time. Never update in place.

### `economic_release_observations`

Actual, revision, unit, provider receipt time, official-source time, source agreement, and lineage.

### `news_documents`

Metadata, dedupe cluster, object reference, source authority, language, and publication/observation times.

### `feature_snapshots`

- `feature_snapshot_id`
- `feature_set_version`
- `entity_type`
- `entity_id`
- `as_of`
- `available_at`
- `values_json`
- `input_manifest_uri`
- `quality_json`
- unique: feature set + entity + `as_of` + version

### `strategy_evaluations`

Candidate state, setup family, policy version, direction, scores, gates, invalidation, targets, expiry, and decision trace ID.

### `risk_decisions`

Portfolio snapshot reference, policy version, approved units, limits consumed, denial reasons, and authorization expiry.

### `order_intents`

Internal intent, idempotency key, candidate/risk references, broker account, order plan, current state, and timestamps.

### `broker_orders`, `fills`, `positions`, `account_snapshots`

Provider-normalized execution and accounting state with raw event references.

### `decision_traces`

Structured trace summary plus immutable object-store reference for the full trace.

### `provider_health`

Channel status, heartbeat time, latency percentiles, errors, clock offset, and current degradation reason.

### `config_versions`, `model_registry`, `dataset_registry`

Immutable governance metadata and artifacts.

## 3. Numeric types

Prices and monetary values use exact numeric columns with instrument-appropriate scale. Raw provider strings are retained. Analytical floating-point features may use double precision but may not become accounting values without explicit conversion.

## 4. Time semantics

Every point-in-time record distinguishes:

- `event_time`: when the market or source says it happened;
- `observed_at`: when this system received it;
- `available_at`: earliest time it was eligible for decisions after processing and watermark rules;
- `created_at`: database creation time.

Backtests query by `available_at`, not merely `event_time`.

## 5. Migrations

- All schema changes use forward migrations.
- Destructive migrations require a two-release expand/migrate/contract process.
- Migration tests run against a copy of representative data.
- Event and API contract changes are versioned independently from table migrations.
- Rollback instructions are required for production migrations.

## 6. Backup and recovery

Define target recovery-point and recovery-time objectives before paper mode. Backups include database, object-store manifests, configuration registry, and model artifacts. Restore drills must prove that open-order reconciliation works after restoring stale state.
