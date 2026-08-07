# Developer Implementation Index

This section converts the system design into a build contract. It tells an engineering team what to implement, in what order, with which boundaries, and how completion is proven.

## Required reading order

1. [Engineering Foundation](01_ENGINEERING_FOUNDATION.md)
2. [Runtime Topology](02_RUNTIME_TOPOLOGY.md)
3. [Domain Model](03_DOMAIN_MODEL.md)
4. [Event Catalog](04_EVENT_CATALOG.md)
5. [Provider Integration Specifications](23_PROVIDER_INTEGRATION_SPECS.md)
6. [Data Pipelines](05_DATA_PIPELINES.md)
7. [Storage Schema](06_STORAGE_SCHEMA.md)
8. [Feature Pipeline](07_FEATURE_PIPELINE.md)
9. [Strategy Engine](08_STRATEGY_ENGINE.md)
10. [Fundamental/NLP Pipeline](09_FUNDAMENTAL_NLP.md)
11. [Risk Engine](10_RISK_ENGINE.md)
12. [Execution Engine](11_EXECUTION_ENGINE.md)
13. [Backtester](12_BACKTESTER.md)
14. [Control-Plane API](13_CONTROL_PLANE_API.md)
15. [Configuration](14_CONFIGURATION.md)
16. [Observability](15_OBSERVABILITY.md)
17. [Testing](16_TESTING.md)
18. [CI/CD](17_CI_CD.md)
19. [Security Threat Model](18_SECURITY_THREAT_MODEL.md)
20. [Failure and Recovery](19_FAILURE_RECOVERY.md)
21. [Deployment Architecture](25_DEPLOYMENT_ARCHITECTURE.md)
22. [Implementation Backlog](20_IMPLEMENTATION_BACKLOG.md)
23. [Acceptance-Test Matrix](21_ACCEPTANCE_TEST_MATRIX.md)
24. [Definition of Done](22_DEFINITION_OF_DONE.md)
25. [Performance Budgets](24_PERFORMANCE_BUDGETS.md)

## Build outcome

The first complete product is not a live bot. It is a deterministic shadow-trading system that:

- ingests point-in-time market, macro, and news streams;
- produces explainable technical and fundamental assessments;
- generates and rejects trade candidates through versioned policies;
- replays the exact same event history with the exact same results;
- records hypothetical fills and costs without sending an order;
- proves that degraded data and provider failures lead to abstention;
- exposes operator status, traces, and emergency controls.

Paper execution follows only after the shadow system satisfies the acceptance matrix. Limited live execution follows only after paper behavior and broker reconciliation satisfy promotion gates.

## Normative architecture

The initial implementation is a Python modular monolith deployed as several process roles from one codebase. Domain logic is pure and provider-independent. External systems are reached only through adapters. Process roles communicate through versioned events and idempotent commands. PostgreSQL/TimescaleDB is the authoritative structured store, an S3-compatible object store retains raw payloads and replay bundles, and NATS JetStream is the recommended event backbone. Local development may use an in-process bus that implements the same interface.

## What developers must not do

- Do not place broker SDK objects in the domain layer.
- Do not let an LLM emit an order intent.
- Do not infer missing event timestamps.
- Do not use completed candles before their close time.
- Do not update historical features in place without preserving the prior version.
- Do not make live mode a configuration typo away from paper mode.
- Do not optimize parameters on the final evaluation period.
- Do not treat broker tick volume as global FX order flow.
- Do not collapse a rejected, unknown, and timed-out order into one status.
