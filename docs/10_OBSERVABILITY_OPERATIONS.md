# 10 — Observability and Operations

## 1. Operational objective

The operator should know what the system sees, why it acted or abstained, what the broker confirms, and whether any dependency is degraded.

## 2. Core dashboards

### Market and data health

- quote freshness;
- spread percentiles;
- provider divergence;
- event-stream lag;
- missing sequences;
- futures contract state;
- calendar/news latency;
- clock drift.

### Strategy

- candidates by state;
- setup family;
- pair and session;
- acceptance/rejection rates;
- confidence distribution;
- technical/fundamental conflicts;
- expected value before cost;
- no-trade reasons.

### Execution

- orders by state;
- acknowledgment latency;
- fill latency;
- slippage;
- rejects;
- partial fills;
- missing protection;
- reconciliation mismatches.

### Risk

- account equity;
- realized/unrealized P/L;
- open stop risk;
- currency exposure;
- correlated exposure;
- event concentration;
- drawdown state;
- circuit-breaker status.

### Models

- calibration;
- feature drift;
- prediction drift;
- abstention;
- champion/challenger comparison;
- version coverage.

## 3. Decision trace

Every candidate has a trace ID linking:

- raw market events;
- macro/news events;
- features;
- zones and liquidity pools;
- model outputs;
- policy gates;
- risk decision;
- order intent;
- broker events;
- fills;
- management actions;
- final attribution.

This trace must be queryable without reconstructing from application logs alone.

## 4. Logs

Use structured logs with:

- timestamp;
- service;
- environment;
- trace ID;
- event ID;
- account alias;
- pair;
- severity;
- message code;
- fields;
- configuration version.

Never log secrets, full tokens, or unnecessary personal data.

## 5. Metrics and service objectives

Example operational objectives:

- broker quote freshness within strategy requirement;
- protective-order verification within strict threshold;
- zero untracked open positions;
- zero duplicate live orders;
- deterministic decision replay;
- bounded event-processing lag;
- rapid kill-switch propagation;
- complete raw-payload retention for audited sources.

SLOs are defined by strategy latency requirements, not generic web-service targets.

## 6. Alerts

Critical:

- unprotected position;
- broker/account mismatch;
- kill switch failed;
- duplicate order;
- margin breach;
- stale executable quotes;
- severe clock drift;
- unknown order state.

High:

- news/calendar outage during enabled event strategy;
- flow feed unavailable;
- slippage above limit;
- repeated rejects;
- drawdown state change;
- model calibration breach.

Medium:

- degraded secondary provider;
- elevated spread;
- reconnect loop;
- noncritical feature lag.

## 7. Runbooks

Required before live:

- global halt;
- cancel all;
- flatten positions;
- broker disconnect;
- missing stop;
- unknown order;
- duplicate position;
- data-provider outage;
- news contradiction;
- clock drift;
- database lag;
- event-bus backlog;
- model rollback;
- configuration rollback;
- credential rotation.

## 8. Daily operating report

- account start/end equity;
- trades and rejected candidates;
- gross and net P/L;
- cost attribution;
- setup attribution;
- event attribution;
- slippage;
- incidents;
- manual interventions;
- risk-state transitions;
- provider health;
- next-session event risk.

## 9. Post-trade review

For each trade:

- thesis;
- expected behavior;
- actual behavior;
- whether all data was available;
- execution quality;
- exit rationale;
- rule adherence;
- counterfactual outcomes;
- lessons.

Automated narrative can summarize, but structured facts remain authoritative.

## 10. Incident severity

- SEV-1: uncontrolled live exposure, missing protection, account compromise.
- SEV-2: wrong order, duplicated order, material reconciliation failure.
- SEV-3: strategy/data outage with no uncontrolled exposure.
- SEV-4: degraded noncritical analytics.

Every SEV-1/2 requires a postmortem and explicit re-enable approval.
