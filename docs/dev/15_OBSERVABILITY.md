# Observability and Decision Tracing

## 1. Telemetry standard

All process roles emit OpenTelemetry traces, metrics, and structured logs. Correlation, causation, event, candidate, risk, order, account, and replay IDs are standard attributes.

## 2. Service-level indicators

### Data

- connection uptime;
- heartbeat age;
- event receipt lag;
- sequence gaps;
- invalid payload rate;
- cross-source divergence;
- watermark lag.

### Decision

- evaluations per instrument/session;
- gate rejection counts;
- candidate rate;
- abstention rate;
- feature missingness;
- policy latency;
- duplicate suppression.

### Risk

- approval/denial rate;
- open and reserved risk;
- currency exposure;
- limit utilization;
- halt state;
- authorization expiry before execution.

### Execution

- request, acknowledgment, fill, and protection latency;
- effective spread and slippage;
- reject/timeout/unknown rates;
- reconciliation mismatches;
- missing-protection duration;
- broker/account stream age.

## 3. Decision trace

A trace contains:

- all input snapshot IDs and availability times;
- policy/model/config versions;
- gate results with codes;
- feature values and lineage;
- score decomposition;
- conflicts and missing inputs;
- expected cost/value calculations;
- candidate, risk, execution, and management transitions;
- narrative rendering derived from structured facts.

The trace is finalized when the candidate is rejected, expires, or the resulting position closes.

## 4. Logging rules

Logs are JSON and contain no secret, raw authorization, full account number, or unlicensed document body. Provider payload bodies live in controlled raw storage and are referenced by hash. Exceptions use stable error codes and safe messages.

## 5. Alerts

Paging alerts:

- unknown broker order state;
- unprotected exposure;
- account mismatch;
- risk engine unavailable in paper/live;
- clock drift beyond limit;
- global data degradation affecting open positions;
- daily loss/drawdown halt;
- unauthorized configuration or mode change.

Ticket-level alerts cover elevated lag, dead letters, model drift, and backfill failures.

## 6. SLO philosophy

Availability SLOs do not pressure the system to trade. Readiness for new orders is a separate SLI and may intentionally be low during unsafe conditions.

## 7. Daily report

The system generates a daily immutable report: provider health, candidates, rejections, approvals, hypothetical/actual orders, P/L and costs, risk use, incidents, configuration changes, and model drift. No-trade days are fully reported.
