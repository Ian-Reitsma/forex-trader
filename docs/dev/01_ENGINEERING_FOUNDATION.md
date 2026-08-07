# Engineering Foundation

## 1. Technology baseline

The implementation SHOULD use Python 3.13 as the initial language baseline because the project combines asynchronous I/O, numerical research, data engineering, and machine-learning workflows. The exact interpreter and all dependencies MUST be locked in source control when code begins.

Recommended foundation:

- package and environment management: `uv` with a committed lockfile;
- type system: Python type hints, strict `mypy`, and Pydantic v2 at I/O boundaries;
- formatting and linting: Ruff;
- tests: pytest, Hypothesis, and contract-test fixtures;
- API: FastAPI for the operator/control plane only;
- database access: SQLAlchemy 2 and Alembic migrations;
- analytical frames: Polars and Arrow; Pandas only when a required library lacks Arrow support;
- event backbone: NATS JetStream in shared environments, in-process implementation for unit tests;
- structured data: PostgreSQL with TimescaleDB extension where available;
- raw data: S3-compatible object storage such as MinIO locally;
- metrics/traces/logs: OpenTelemetry, Prometheus-compatible metrics, and structured JSON logs.

These are architectural defaults, not permission to import libraries across boundaries.

## 2. Architectural style

Use a modular monolith with hexagonal boundaries. One repository produces multiple process roles, but all roles depend on the same domain contracts.

```text
interfaces -> application -> domain
adapters   -> application -> domain
infrastructure implements ports declared inward
```

The domain package MUST NOT import FastAPI, SQLAlchemy, broker SDKs, NATS clients, cloud SDKs, or model-provider SDKs.

## 3. Process roles

The same build artifact starts with a role argument:

- `market-ingestor`
- `macro-news-ingestor`
- `bar-feature-worker`
- `fundamental-worker`
- `decision-worker`
- `risk-worker`
- `execution-worker`
- `reconciliation-worker`
- `control-api`
- `replay-worker`
- `scheduler`

A role loads only the credentials and permissions it requires. The `decision-worker` has no broker secret. The `execution-worker` cannot change strategy configuration. The `control-api` cannot fabricate risk approval.

## 4. Package boundaries

```text
src/forex_trader/
  domain/           pure entities, value objects, policies, domain events
  application/      use cases, ports, orchestration, command handlers
  adapters/         OANDA, IBKR, CME, Trading Economics, official sources
  infrastructure/   database, bus, object store, telemetry, secret backends
  services/         process-role composition roots
  api/              operator API schemas and routes
  research/         offline experiments; never imported by live roles
```

Imports are checked in CI with an architecture test. `research` may depend on production domain contracts; production modules MUST NOT depend on `research`.

## 5. Coding rules for future implementation

- Monetary values use `Decimal` or integer minor units, never binary float at accounting boundaries.
- Prices and quantities carry instrument metadata and precision.
- Timestamps are timezone-aware UTC and represented with nanosecond-capable storage when provider precision requires it.
- Domain IDs are UUIDv7 or a monotonic equivalent; provider IDs are stored separately.
- Every external call has a timeout, retry policy, idempotency policy, and telemetry.
- Retryable errors and terminal errors are different types.
- `None` cannot mean unknown, not applicable, and unavailable simultaneously; use explicit enums.
- Every policy is versioned and immutable after use.
- Events are append-only. Corrections arrive as new events referencing prior events.

## 6. Repository bootstrap deliverables

Phase 1 creates, but does not yet implement trading behavior:

- locked toolchain;
- package skeleton and dependency-boundary tests;
- configuration loader with environment validation;
- event envelope and core IDs;
- structured logging and trace context;
- database migration framework;
- in-process and NATS event-bus ports;
- object-store port;
- deterministic clock and ID providers for tests;
- CI pipeline;
- synthetic test fixtures;
- command-line entry points for process roles;
- health endpoints.

## 7. Local developer experience

One command SHOULD start local infrastructure, apply migrations, load synthetic fixtures, and launch shadow mode. No real provider credential is required for the default path. A second explicit profile enables provider sandboxes.

The local stack includes PostgreSQL, NATS, MinIO, Prometheus, and a telemetry collector. Developers can replace infrastructure with in-memory implementations for fast unit tests.

## 8. Quality gates

A change cannot merge unless:

- formatting, linting, typing, unit, contract, architecture, and migration tests pass;
- generated schemas are unchanged or intentionally versioned;
- new external payloads include captured fixtures with secrets removed;
- decision behavior changes include golden-trace updates and rationale;
- risk behavior changes are reviewed separately from strategy changes;
- no production package imports a research package.
