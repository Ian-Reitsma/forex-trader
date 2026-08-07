# Independent Risk Engine

## 1. Independence

The risk engine is a separate application boundary and process role. It consumes candidates and authoritative portfolio state. Strategy code cannot import its implementation or fabricate approval. Execution verifies the signed or otherwise integrity-protected authorization.

## 2. Inputs

- finalized candidate and expiry;
- account NAV, balance, margin, and currency;
- positions, orders, stops, and pending intents;
- currency-leg exposure;
- realized and unrealized P/L;
- daily and peak drawdown state;
- event calendar and concentration;
- provider/broker health;
- execution-cost estimate;
- risk-policy version;
- operating mode.

## 3. Gate order

1. global and account halts;
2. authorization environment and account match;
3. candidate freshness and policy allowlist;
4. stop validity and loss calculation;
5. margin and available-unit constraints;
6. per-trade risk cap;
7. pair exposure cap;
8. currency-leg cap;
9. correlated cluster cap;
10. event concentration cap;
11. daily loss and drawdown cap;
12. order-rate and operational controls;
13. size calculation and rounding;
14. final cost and minimum-reward check.

The first denial is recorded, but all applicable denials SHOULD be returned for diagnosis.

## 4. Position sizing

```text
risk_amount = min(
  nav * per_trade_risk_fraction,
  remaining_daily_risk,
  remaining_cluster_risk,
  policy_absolute_cap
)

loss_per_unit = stop_distance converted to account currency
raw_units = risk_amount / loss_per_unit
approved_units = floor_to_broker_increment(raw_units * execution_haircut)
```

Risk uses the stop-side executable price and stressed slippage. Size is zero when conversion or stop loss cannot be computed confidently.

## 5. Currency exposure

Every FX position decomposes into base and quote legs. Pending orders and stop-loss gap risk are included. The engine aggregates net and gross exposure by currency and by correlated policy cluster.

## 6. Authorization contract

An approval includes:

- authorization ID;
- candidate ID and hash;
- account/environment;
- approved side and maximum units;
- approved entry-price range;
- stop and maximum loss;
- required protection;
- risk limits consumed;
- issued and expiry times;
- risk-policy version;
- portfolio snapshot ID;
- integrity signature or trusted-store reference.

Any material execution change requires reauthorization.

## 7. Halts

Halt scopes:

- strategy;
- instrument;
- currency;
- account;
- provider-dependent strategies;
- global.

Release may be automatic only for short, unambiguous data freshness conditions explicitly approved by policy. Loss, reconciliation, protection, security, and operator halts require human release.

## 8. Loss controls

Initial policy values remain configuration requiring governance approval, not hardcoded constants. The engine supports:

- per-trade risk;
- simultaneous open risk;
- realized daily loss;
- total daily P/L;
- trailing drawdown;
- loss streak observation;
- event-gap stress;
- weekend/rollover exposure;
- margin utilization.

## 9. Tests

- exact loss calculations across quote orientations and account currencies;
- rounding never increases risk above cap;
- pending and filled exposure aggregate correctly;
- stale authorizations fail;
- policy changes invalidate old authorizations when required;
- stop widening fails;
- duplicate candidates do not double-reserve risk;
- restart reconstructs reserved and consumed risk from durable state.
