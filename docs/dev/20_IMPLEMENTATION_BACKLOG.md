# Developer Implementation Backlog

This backlog is ordered. A team should not begin later execution epics merely because they are more visible.

## Epic 0 — Specification lock

- resolve open ADRs and provider choices;
- approve canonical schemas and event names;
- approve initial instruments, sessions, and one strategy family;
- approve risk-policy structure and paper limits;
- document data licenses and retention;
- create acceptance-test ownership.

Exit: all Phase 0 items in the roadmap are accepted.

## Epic 1 — Repository foundation

- bootstrap Python package and `uv` lock;
- configure Ruff, strict mypy, pytest, Hypothesis;
- add architecture import tests;
- add process-role CLI skeletons;
- implement typed configuration and mode isolation;
- implement IDs, clock, event envelope, errors;
- wire structured logs and OpenTelemetry;
- create CI and SBOM.

Exit: synthetic event can traverse in-process bus with deterministic trace.

## Epic 2 — Persistence and messaging

- PostgreSQL/Timescale migrations;
- inbox/outbox pattern;
- NATS JetStream adapter;
- object-store adapter;
- schema registry and compatibility CI;
- replay bundle format;
- backup/restore smoke test.

Exit: duplicate delivery changes state once and replay is deterministic.

## Epic 3 — OANDA market data

- account/instrument metadata mapping;
- pricing stream adapter and heartbeat monitor;
- historical candle/backfill adapter;
- raw archival and normalized quotes;
- data quality/gap metrics;
- reconnect and checkpoint logic;
- synthetic and practice fixtures.

Exit: 24-hour shadow capture with documented gaps and replay parity.

## Epic 4 — Bars and technical features

- watermark-aware bar builder;
- session calendar;
- volatility/spread regimes;
- structure and swing detector;
- zone detector;
- liquidity map and sweep/reclaim detector;
- feature snapshots and lineage;
- human-label comparison tool.

Exit: no-future tests and golden scenarios pass.

## Epic 5 — Macro/calendar/news

- Trading Economics calendar snapshots and streaming release adapter;
- official-source fetch framework;
- news ingestion and dedupe;
- economic surprise model;
- central-bank document diff/extraction;
- currency vectors and event windows;
- model/prompt registry and abstention.

Exit: historical event replay reproduces point-in-time assessments.

## Epic 6 — Order-flow proxy

- CME/vendor connection and contract reference data;
- futures/spot mapping and orientation;
- roll handling;
- volume/delta/profile/VWAP features supported by purchased feed;
- quality and fallback policies.

Exit: flow-required policy disables correctly during degradation and roll.

## Epic 7 — Strategy and risk

- policy engine and state persistence;
- sweep/reclaim v1 policy;
- rejection taxonomy and traces;
- portfolio/currency risk book;
- size and authorization workflow;
- halt service;
- golden and property tests.

Exit: complete shadow candidate-to-risk trace with no broker writes.

## Epic 8 — Backtester and shadow operations

- replay clock/scheduler;
- simulated broker and cost models;
- experiment registry/reports;
- control-plane read APIs;
- dashboards and alerts;
- 30-day shadow soak and incident drills.

Exit: acceptance gates for shadow pass.

## Epic 9 — Paper execution

- OANDA practice order adapter;
- order lifecycle and idempotency;
- transaction stream and account-change reconciliation;
- protection verification;
- emergency controls;
- paper E2E and chaos tests.

Exit: all paper acceptance tests pass across planned order types.

## Epic 10 — Limited live readiness

- separate live infrastructure and identities;
- two-person activation workflow;
- reduced pair/session/risk configuration;
- live incident and recovery rehearsals;
- governance sign-off.

Exit: explicit human approval; no automatic scaling.
