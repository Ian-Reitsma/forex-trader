# 07 — Execution and Broker Architecture

## 1. Principle

The broker is the source of truth for orders, fills, positions, and account state. Internal state is a projection that must be continuously reconciled.

## 2. Broker abstraction

The strategy engine emits a broker-neutral `OrderIntent`. The broker adapter converts it into venue-specific requests.

Order intent includes:

- idempotency key;
- account;
- pair;
- direction;
- units;
- entry style;
- maximum acceptable price/slippage;
- time in force;
- stop specification;
- target specification;
- strategy and decision IDs;
- expiration;
- emergency handling policy.

## 3. Recommended first broker

OANDA v20 is a reasonable first implementation target because its API exposes real-time rates, historical pricing, account data, order creation/modification/closure, and a practice environment. The architecture must not depend on OANDA-specific object names outside the adapter.

Interactive Brokers is a strong alternative for multi-asset expansion and paper/live support, but deployment and market-data entitlements differ. Both should be treated as adapters, not the domain model.

## 4. Pre-trade execution gate

Immediately before submission, re-evaluate:

- live bid/ask;
- spread;
- quote age;
- short-horizon volatility;
- estimated slippage;
- available margin;
- account mode;
- current positions;
- duplicate intent;
- target distance;
- stop distance;
- broker health;
- event risk;
- portfolio risk.

A candidate can be approved by strategy and rejected by execution.

## 5. Order types

Research should compare:

- market;
- limit;
- market-if-touched;
- stop;
- stop-limit where supported.

The system must model fill probability and adverse selection. A limit order is not “free slippage”; it can miss the trade or fill when conditions worsen.

## 6. Protective orders

Preferred order construction attaches or immediately creates:

- stop loss;
- take profit where policy requires;
- optional trailing logic only when validated.

The engine verifies broker acknowledgment. If protection cannot be confirmed within a strict interval, the emergency policy may cancel/close.

## 7. Idempotency

Every order intent has a deterministic unique ID. Retries must not create duplicate positions.

The adapter stores:

- request;
- response;
- provider request ID;
- broker order ID;
- transaction IDs;
- retry count;
- final status.

## 8. Order state machine

```text
CREATED
→ VALIDATED
→ SUBMITTING
→ ACKNOWLEDGED
→ PARTIALLY_FILLED
→ FILLED
→ PROTECTED
→ CLOSING
→ CLOSED
```

Error states:

- `REJECTED`
- `CANCEL_PENDING`
- `CANCELLED`
- `UNKNOWN`
- `RECONCILIATION_REQUIRED`
- `EMERGENCY_CLOSE`

Unknown is treated as dangerous, not as rejected.

## 9. Reconciliation

Use both:

- streaming transaction/order updates;
- periodic authoritative snapshots.

Reconcile:

- open orders;
- positions;
- units;
- average price;
- realized and unrealized P/L;
- stop and target presence;
- margin;
- account NAV;
- financing and fees.

Any unexplained mismatch can halt new trading.

## 10. Execution-cost model

Estimate before trade and measure after trade:

- quoted spread;
- effective spread;
- slippage;
- market impact;
- latency cost;
- rejects;
- partial fills;
- financing;
- commissions;
- conversion cost.

Cost models are conditioned on pair, session, volatility, event proximity, order type, size, and broker.

## 11. Position sizing

Position size follows:

```text
risk_budget
÷ stop_distance_in_account_currency
× liquidity_and_execution_adjustment
× regime_adjustment
× confidence_cap
```

Confidence never increases size beyond hard risk caps. The stop is chosen by structure first; units adapt to the stop.

## 12. Currency exposure accounting

A EUR/USD long is long EUR and short USD. Portfolio controls aggregate each currency leg across pairs. The system prevents accidental concentration through apparently different instruments.

## 13. Latency measurement

Measure:

- source event to receipt;
- receipt to feature;
- feature to decision;
- decision to risk approval;
- approval to broker request;
- request to acknowledgment;
- acknowledgment to fill;
- fill to protective-order confirmation.

Latency distributions, not averages, drive controls.

## 14. Degraded-mode behavior

- Broker quotes stale: halt new orders.
- Account stream down but REST healthy: reduced mode with tighter controls.
- REST down but stream alive: no new orders; manage known positions cautiously.
- Position mismatch: halt and reconcile.
- Stop missing: emergency repair or flatten.
- News feed missing: switch affected strategies to blackout.
- Order-flow feed missing: disable flow-required setups.
- Clock drift: halt event-driven strategies.

## 15. Emergency controls

- manual global kill switch;
- automated daily-loss halt;
- automated drawdown halt;
- stale-data halt;
- broker-disconnect halt;
- runaway-order-rate halt;
- duplicate-position halt;
- margin-risk halt;
- emergency flatten;
- cancel-all.

Emergency actions are tested in paper mode on a schedule.
