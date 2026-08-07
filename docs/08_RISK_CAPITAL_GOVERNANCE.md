# 08 — Risk, Capital, and Governance

## 1. Risk objective

Survival precedes optimization. The system must be able to be wrong repeatedly without threatening the account or creating uncontrolled exposure.

## 2. Risk layers

1. Trade risk.
2. Pair risk.
3. Currency-leg risk.
4. Correlation and factor risk.
5. Session and event risk.
6. Daily and rolling drawdown risk.
7. Broker and operational risk.
8. Model and data risk.

## 3. Initial research limits

Values below are conservative research starting points, not promises or final production settings:

- risk per trade: 0.10%–0.25% of current risk equity;
- aggregate open risk: 0.50%–1.00%;
- daily realized plus marked loss halt: approximately 1%;
- weekly drawdown review threshold: approximately 2%–3%;
- hard maximum leverage below broker maximum;
- maximum simultaneous positions per currency;
- no martingale;
- no risk increase after a loss;
- no averaging into an invalidated setup.

Final limits must follow backtests, paper behavior, account size, broker rules, and operator tolerance.

## 4. Risk equity

Position sizing uses a conservative risk-equity figure, potentially the minimum of:

- current NAV;
- start-of-day equity adjusted for realized loss;
- high-water-mark equity less risk reserve.

This prevents unrealized gains from immediately and aggressively increasing size.

## 5. Stop integrity

Every trade has a predefined invalidation. Rules:

- no widening after entry;
- no removing protection;
- no converting a scalp into an indefinite hold;
- no adding after invalidation;
- stop movement only reduces risk and must be structurally justified;
- gap/slippage risk is acknowledged in sizing.

## 6. Portfolio exposure

Track net and gross exposure by:

- currency;
- USD factor;
- risk-on/risk-off factor;
- carry factor;
- commodity factor;
- European currency factor;
- JPY funding factor;
- correlated pair cluster.

Examples:

- long EUR/USD and long GBP/USD both create short USD exposure;
- long AUD/USD and long NZD/USD may duplicate commodity/risk exposure;
- long EUR/JPY and long GBP/JPY duplicate short JPY exposure.

## 7. Event concentration

Before major events, aggregate:

- direct currency exposure;
- correlated cross exposure;
- open stop risk;
- slippage stress;
- likely spread widening.

A portfolio may be within ordinary limits but unsafe for a concentrated event.

## 8. Stress testing

Pre-trade and portfolio stress scenarios:

- spread doubles or triples;
- stop slips by event-specific percentile;
- broker disconnects;
- correlated pairs move together;
- news is reversed or corrected;
- market gaps through stop;
- liquidity proxy disappears;
- order is partially filled;
- protective order is delayed;
- quote source diverges from broker.

## 9. Drawdown controls

State transitions:

- `NORMAL`
- `CAUTION`
- `REDUCED_RISK`
- `HALTED`
- `REVIEW_REQUIRED`

Triggers may use:

- daily loss;
- rolling loss;
- peak-to-trough drawdown;
- consecutive losses;
- cost deterioration;
- model calibration degradation;
- abnormal rejection rate;
- operational incidents.

Consecutive losses alone should not imply strategy failure, but can reveal an unrecognized regime change.

## 10. Risk-adjusted confidence

Model confidence may only reduce risk below the hard cap unless governance explicitly validates a sizing schedule. A high score does not justify concentration.

## 11. Model risk

Controls:

- champion/challenger evaluation;
- versioned models;
- out-of-sample validation;
- drift monitoring;
- calibration monitoring;
- feature-availability checks;
- abstention;
- rollback;
- no online weight changes in live mode.

## 12. Data risk

Every critical feature carries:

- source;
- freshness;
- quality;
- fallback;
- confidence.

A trade cannot be “high confidence” if a critical input is degraded.

## 13. Operational risk

Controls:

- least-privilege credentials;
- separate practice and live secrets;
- account allowlists;
- order-rate caps;
- deployment approvals;
- change freeze around major events;
- tested rollback;
- incident logging;
- reconciliation.

## 14. Promotion governance

Live promotion requires approval of:

- strategy specification;
- data licenses;
- backtest integrity;
- paper results;
- execution stress tests;
- kill-switch tests;
- monitoring;
- incident runbooks;
- risk limits;
- operator access.

No single profitable chart or short paper run can waive these gates.

## 15. Human authority

Humans may:

- halt;
- reduce risk;
- close positions;
- disable a strategy;
- roll back a deployment.

Humans may not silently override logs, erase losses, or relabel trades. Manual intervention is recorded as an event.
