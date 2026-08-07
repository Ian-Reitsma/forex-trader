# Sequence Flows

## Candidate to protected position

```mermaid
sequenceDiagram
  participant M as Market/Feature Worker
  participant S as Strategy
  participant R as Risk
  participant E as Execution
  participant B as Broker
  participant C as Reconciliation
  M->>S: immutable context snapshots
  S->>S: hard gates and policy state
  S-->>R: TradeCandidate
  R->>R: portfolio and limit evaluation
  R-->>E: RiskAuthorization
  E->>E: quote/account preflight
  E->>B: idempotent order request
  B-->>E: acknowledgment/transaction
  E->>B: protection request if not attached
  B-->>C: transaction and position state
  C-->>E: protection confirmed
  C-->>R: portfolio snapshot
```

## Timeout after submission

```mermaid
sequenceDiagram
  participant E as Execution
  participant B as Broker
  participant C as Reconciliation
  E->>B: order with client ID
  B--xE: HTTP timeout
  E->>E: state = UNKNOWN; block retry
  E->>B: query order/client ID and transactions
  B-->>C: authoritative fill/order state
  C-->>E: resolved ACK/FILL or no order
  E->>E: continue lifecycle or retry same ID
```

## Economic release

```mermaid
sequenceDiagram
  participant T as Calendar Provider
  participant O as Official Source
  participant F as Fundamental Worker
  participant S as Strategy
  T-->>F: pre-release snapshot
  T-->>F: actual observed
  O-->>F: official release/verification
  F->>F: surprise, revision, stance, confidence
  F-->>S: FundamentalAssessment with availability time
  S->>S: event policy and technical-location fusion
```
