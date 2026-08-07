# Execution and Reconciliation Engine

## 1. Responsibilities

The execution engine converts an authorized internal order plan into provider requests, tracks uncertain outcomes, confirms protection, and emits normalized broker events. It does not choose direction or override risk.

## 2. Submission workflow

```text
receive intent
-> verify schema and environment
-> verify risk authorization integrity/freshness
-> refresh quote and account state
-> run execution gates
-> reserve idempotency key
-> submit provider request
-> persist request/response and provider IDs
-> consume transaction/order events
-> confirm fill and protection
-> reconcile authoritative snapshot
```

## 3. Execution gates

- broker session authenticated and healthy;
- quote fresh and tradeable;
- spread and estimated slippage acceptable;
- entry still within authorized range;
- candidate and authorization unexpired;
- no duplicate intent or equivalent open exposure;
- margin and account state still valid;
- protective order supported and constructible;
- provider rate limit available;
- clock offset within tolerance;
- no newer halt.

## 4. Order plan

The internal plan contains side, maximum units, order style, price constraints, time in force, stop, target policy, client idempotency tag, and expiry. Provider adapters map this to supported semantics and return a capability error rather than silently approximating unsupported behavior.

## 5. State machine

```text
CREATED -> VALIDATED -> SUBMITTING -> ACKNOWLEDGED
-> PARTIALLY_FILLED -> FILLED -> PROTECTION_PENDING -> PROTECTED
-> CLOSING -> CLOSED
```

Terminal or exceptional states:

- `REJECTED`
- `CANCEL_PENDING`
- `CANCELLED`
- `EXPIRED`
- `UNKNOWN`
- `RECONCILIATION_REQUIRED`
- `EMERGENCY_REPAIR`
- `EMERGENCY_CLOSE`

`UNKNOWN` means the provider may have acted. The engine must query/reconcile before retrying.

## 6. Idempotency

The same internal intent always maps to the same client order identifier where the broker supports it. The database enforces uniqueness before network submission. Retries reuse the identifier and inspect provider state.

## 7. Protection

Preferred implementation uses broker-native attached stop and target instructions when semantics are proven. If separate protection is required:

- the fill event starts a strict protection timer;
- stop creation is highest priority;
- failures trigger repair retries within a bounded window;
- unresolved missing protection triggers emergency close and a trading halt;
- protection is verified from the broker's authoritative state, not only request success.

## 8. Reconciliation

Streaming updates provide low latency; periodic snapshots provide authority. Reconciliation compares orders, trades/positions, units, average price, protection, P/L, fees, margin, and last transaction IDs.

Mismatch classes:

- benign timing lag;
- local missing event recoverable from provider history;
- provider object unmapped;
- duplicate local lifecycle;
- quantity/price mismatch;
- missing protection;
- unknown open exposure;
- account balance inconsistency.

Material mismatches halt new orders.

## 9. Cost attribution

For each fill record quoted spread, arrival price, decision price, submitted price, fill price, slippage, latency, commissions, financing, conversion cost, and opportunity cost for missed limits. Costs are grouped by pair, session, event proximity, volatility, size, order type, and provider.

## 10. Restart recovery

On startup the execution role is read-only until it:

- loads unresolved local lifecycles;
- fetches account/orders/positions;
- catches up transaction history from the last durable provider transaction ID;
- maps provider objects to internal IDs;
- repairs or halts on mismatches;
- confirms protection;
- receives explicit trading readiness.
