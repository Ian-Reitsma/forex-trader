# Control-Plane API Contract

## 1. Scope

The API is for operators, observability, replay control, and audit retrieval. Strategies do not call it to exchange market events. It is not a public trading API.

## 2. Authentication and authorization

Use an identity-aware proxy or OIDC. Roles:

- `viewer`: status, traces, positions, reports;
- `researcher`: create replay runs and view research data;
- `operator`: paper-mode controls and approved halt actions;
- `risk_admin`: risk policy and halt release workflow;
- `live_admin`: limited-live activation through multi-party approval;
- `auditor`: immutable audit access.

Sensitive actions require recent authentication, reason, ticket/reference, and audit event. Live activation and global halt release require two-person approval.

## 3. Endpoints

### Health

- `GET /health/live`
- `GET /health/ready`
- `GET /v1/system/status`
- `GET /v1/providers`

### Decisions and audit

- `GET /v1/candidates`
- `GET /v1/candidates/{candidate_id}`
- `GET /v1/decisions/{decision_trace_id}`
- `GET /v1/risk-decisions/{risk_decision_id}`
- `GET /v1/orders/{order_intent_id}`
- `GET /v1/positions`

### Research

- `POST /v1/replays`
- `GET /v1/replays/{run_id}`
- `POST /v1/replays/{run_id}/cancel`
- `GET /v1/datasets`
- `GET /v1/policies`

### Controls

- `POST /v1/halts`
- `POST /v1/halts/{halt_id}/release-request`
- `POST /v1/halts/{halt_id}/approve-release`
- `POST /v1/modes/activation-request`
- `POST /v1/modes/{request_id}/approve`
- `POST /v1/emergency/cancel-all`
- `POST /v1/emergency/flatten`

Emergency endpoints remain disabled until the broker adapter and paper tests are implemented.

## 4. Response standards

- problem-details JSON for errors;
- correlation ID in every response;
- cursor pagination for event-like resources;
- UTC RFC 3339 timestamps;
- explicit schema version;
- no secrets or raw provider authorization headers;
- large traces returned by signed object-store references with short expiry.

## 5. Concurrency

Mutations accept an idempotency key. State-changing requests use expected version or ETag to prevent lost updates. Approval workflows are append-only.

## 6. Streaming UI updates

Server-sent events or WebSocket may deliver status changes to an operator dashboard. This channel is observational and cannot submit orders.

## 7. API acceptance tests

- unauthorized and wrong-role requests fail;
- idempotent retries return the same workflow;
- stale expected versions fail;
- every mutation creates an audit event;
- live activation cannot be single-step;
- a global halt blocks new risk authorizations before the API reports success.
