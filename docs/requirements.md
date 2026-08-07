# Functional and Non-Functional Requirements

## Functional requirements

### Market data

- Ingest executable bid/ask and account transactions.
- Ingest historical data for replay.
- Support futures/institutional order-flow proxy.
- Detect gaps, staleness, and source disagreement.
- Build reproducible bars and features.

### Fundamentals and news

- Maintain a scheduled event calendar.
- Ingest actual, consensus, previous, and revisions.
- Store consensus snapshots point in time.
- Parse central-bank communications.
- Classify material news by currency and event type.
- Support abstention and contradiction handling.

### Technicals

- Detect structure, zones, liquidity pools, sweeps, and confirmation.
- Maintain multi-timeframe context.
- Compute volatility and spread regimes.
- Integrate order-flow proxy and confidence.

### Decision

- Use setup state machines.
- Apply hard gates.
- Select regime-specific policy.
- Preserve evidence conflict.
- Calculate cost-aware expected value.
- Emit structured trade candidates or rejection reasons.

### Risk

- Size from structural stop and risk budget.
- Aggregate currency and correlated exposure.
- Enforce daily, rolling, event, and operational limits.
- Provide automatic and manual halt.
- Prevent martingale and stop widening.

### Execution

- Support paper and live adapters.
- Submit idempotent orders.
- Verify protective orders.
- Reconcile broker state.
- Handle rejects, partial fills, disconnects, and unknown states.
- Measure slippage and latency.

### Research

- Point-in-time replay.
- Realistic execution simulation.
- Walk-forward validation.
- Reproducible experiments.
- Attribution by setup, event, session, pair, and cost.

### Operations

- Decision traces.
- Dashboards.
- Alerts.
- Incident runbooks.
- Daily reports.
- Audit log.

## Non-functional requirements

### Correctness

- Decimal-safe monetary calculations.
- Explicit quote orientation.
- Deterministic replay.
- Typed schemas.
- Idempotent writes.

### Reliability

- Conservative degradation.
- No new trades on critical stale data.
- Automatic reconciliation.
- Tested recovery.
- No single silent point of failure for critical state.

### Performance

- Latency budgets by data class.
- Protective execution prioritized over analytics.
- Backpressure and bounded queues.
- No blocking LLM call in emergency path.

### Security

- least privilege;
- managed secrets;
- environment separation;
- protected live mode;
- auditable changes;
- dependency scanning.

### Explainability

- Every decision has facts, versions, and rejection reasons.
- Narratives cannot contradict structured output.
- Model confidence is calibrated.

### Maintainability

- provider adapters isolated;
- domain independent of SDKs;
- tests at boundaries;
- architecture decisions recorded;
- configuration versioned.
