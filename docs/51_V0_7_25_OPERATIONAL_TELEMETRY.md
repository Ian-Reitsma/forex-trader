# 51 — v0.7.25 Durable Operational Telemetry

## Purpose

v0.7.25 closes the first operational-observability tranche from the post-v0.7.22 audit. The goal is not to add another dashboard-only cache. The goal is to make the same durable repository that governs trading also emit a queryable record of what the runtime decided, why risk was denied, whether broker state is uncertain, whether providers are degraded, and whether reconciliation or persistent halts make the system unsafe to operate.

This release does not expand strategy authority. `sweep_reclaim:v1` remains the only Practice-authorized setup family. The telemetry subsystem is observational only: it cannot create a `TradeCandidate`, grant a `RiskAuthorization`, change strategy authority, clear a halt, or submit an order.

## Durable event stream

`AdvancedTradingRepository` now owns an `operational_events` table alongside the existing decisions, halts, readiness, setup lifecycle, risk state, broker transactions, and cost evidence.

Saving a decision trace derives deterministic, idempotent events for:

- decision disposition and rejection code;
- selected strategy policy and regime;
- independent confirmation counts;
- risk grant/denial, risk amount, risk-policy identity, consumed limits, and veto reasons;
- execution status and protection state;
- point-in-time provider health, rate limiting, and provider detail;
- external-context runtime errors.

Because trace-derived event IDs are deterministic, the base `TradingEngine` save followed by the enriched `FxTradingEngine` save updates the same operational records rather than double-counting one decision.

Persistent halt changes and execution-readiness updates are also written to the operational stream. The authoritative current halt/readiness state remains in the existing control tables; telemetry does not replace the safety mechanism it observes.

## Operational summary

`OperationalTelemetryService` projects a bounded time window over durable events and current halt/readiness state. It reports:

- event and severity counts;
- decisions by disposition;
- rejection-code concentration;
- selected strategy-policy concentration;
- regime mix;
- risk grants/denials;
- normalized risk-veto reasons;
- execution statuses;
- latest provider states;
- active persistent halts;
- broker reconciliation readiness;
- current operational alerts.

Dynamic risk messages are normalized only enough to aggregate the same veto family. The raw event payload remains available through the event endpoint.

## Alert policy

The initial policy emits critical alerts for:

- active persistent trading halts;
- broker accounts that are not reconciliation-ready;
- unresolved execution states (`unknown`, `reconciliation_required`, or `emergency_close`);
- unavailable providers.

It emits error alerts for:

- provider runtime errors;
- decision-evaluation runtime errors.

It emits warnings for:

- degraded providers;
- provider rate limiting, even when the provider's nominal state is otherwise healthy.

These are local deterministic operational alerts, not an external paging service. Email/SMS/PagerDuty/Slack routing remains deployment work.

## Protected API surfaces

The operator API now exposes three read-only protected surfaces:

```text
GET /v1/operations/summary?hours=24
GET /v1/operations/events?hours=24&limit=200&category=...&severity=...
GET /v1/operations/metrics?hours=24
```

The first two return JSON. The metrics endpoint returns Prometheus-compatible text including:

- `forex_operational_events_total{category=...}`;
- `forex_operational_severity_total{severity=...}`;
- `forex_decisions_total{disposition=...}`;
- `forex_risk_authorizations_total{disposition=...}`;
- `forex_execution_status_total{status=...}`;
- `forex_provider_state{provider=...,state=...}`;
- `forex_active_halts`;
- `forex_execution_not_ready_accounts`;
- `forex_operational_alerts{severity=...}`.

These endpoints use the same bearer-token protection as the existing control API. A missing control-plane token disables protected routes outside the explicit local-test escape hatch.

## What this release does not claim

This release implements a durable local telemetry backbone and a machine-readable metrics surface. It does not claim that scaled production operations are complete.

Still required before high-volume deployment:

- Prometheus/Grafana or equivalent external collection and dashboards;
- external alert routing and escalation policies;
- retention/downsampling policy for long-lived high-volume telemetry;
- PostgreSQL/TimescaleDB or equivalent scale-out storage if SQLite becomes a bottleneck;
- a durable distributed event bus if the architecture becomes multi-process/multi-host;
- deployment SLOs, backup/restore testing, failover drills, and incident runbooks;
- provider-specific rate-limit budgets and service-level objectives;
- authenticated OANDA Practice operating evidence during open markets.

## Closed-market boundary

The development date remains Saturday, August 8, 2026. The FX market is closed, so v0.7.25 is being validated as software/infrastructure rather than using stale weekend conditions to manufacture representative scalping execution evidence.

The next broker evidence sequence remains:

```text
authenticated read-only OANDA Practice probe
-> reconciliation
-> all-pair shadow scan
-> separately gated protected minimum-size Practice round trip
-> capped Practice campaign
-> mature outcome labeling and after-cost research
```

## Validation

The release adds a dedicated Python 3.11/3.13 operations gate for the new domain/service surfaces and focused repository/API behavior. The existing repository-wide CI, v0.7.24 risk/validation gate, annotation-integrity workflow, coverage threshold, secret scan, and protected-paper smoke remain in force.

CI establishes implementation integrity. It does not establish a profitable edge or substitute for real provider/broker operating evidence.
