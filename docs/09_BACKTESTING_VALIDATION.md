# 09 — Backtesting and Validation

## 1. Principle

A backtest is a simulation of information, execution, and policy as they existed at the time. It is not a chart with future-cleaned data and frictionless fills.

## 2. Required simulator properties

- event driven;
- bid/ask aware;
- point-in-time calendar and news;
- source latency;
- variable spread;
- slippage;
- partial fills where relevant;
- order rejects;
- session calendars;
- contract rolls;
- financing and fees;
- portfolio exposure;
- broker rules;
- deterministic replay.

## 3. Data leakage controls

Prohibited:

- using revised economic data as the original release;
- using final consensus instead of the snapshot known before release;
- identifying a zone with candles that occurred after the decision;
- using future swing pivots without confirmation delay;
- training and testing overlapping event windows;
- selecting parameters on the test set;
- using corrected timestamps without modeling original arrival.

## 4. Dataset design

Partition by time, not random rows.

Suggested structure:

- development period;
- validation period;
- untouched test period;
- rolling walk-forward windows;
- crisis and shock holdouts;
- pair-specific and cross-pair tests.

Use purging and embargo around overlapping labels and events.

## 5. Baselines

Compare against simple alternatives:

- no-trade;
- random direction at same times;
- technical-only;
- fundamental-only;
- session-only;
- zone touch without confirmation;
- sweep without flow confirmation;
- fixed spread versus realistic spread;
- simple trend filter;
- buy-and-hold is generally not a relevant scalp baseline, but currency carry/context benchmarks may be.

A complex model must beat a simpler model after costs and uncertainty.

## 6. Metrics

### Trading

- net expectancy;
- profit factor;
- average win/loss;
- win rate;
- payoff ratio;
- maximum drawdown;
- time under water;
- Sharpe/Sortino with caveats;
- tail loss;
- turnover;
- exposure;
- cost as percentage of gross edge.

### Prediction

- precision and recall by setup;
- calibration;
- Brier score;
- log loss;
- lift over baseline;
- confidence intervals.

### Execution

- fill rate;
- slippage distribution;
- effective spread;
- rejection rate;
- latency distribution;
- target/stop race behavior.

### Stability

- by year;
- pair;
- session;
- volatility regime;
- event type;
- trend/range regime;
- provider;
- parameter neighborhood.

## 7. Statistical uncertainty

Report:

- bootstrap confidence intervals;
- block bootstrap for serial dependence;
- Monte Carlo trade-order reshuffling;
- parameter sensitivity;
- multiple-testing correction or conservative research accounting;
- probability of backtest overfitting where applicable.

Do not present a single equity curve as sufficient evidence.

## 8. Event-study framework

For each release class:

- pre-event spread;
- source latency;
- surprise distribution;
- first-move magnitude;
- reversal probability;
- time to spread normalization;
- first-pullback behavior;
- continuation probability;
- maximum favorable/adverse excursion;
- outcome by technical location;
- outcome by positioning and cross-asset response.

This determines blackout, reaction, continuation, or failure policies.

## 9. Technical-label validation

Zone, sweep, and structure algorithms must be evaluated against:

- reproducibility;
- blinded human labels;
- inter-rater disagreement;
- outcome relevance;
- parameter stability.

Human agreement is not proof of profitability, but reveals whether the algorithm matches the intended concept.

## 10. Paper validation

Paper trading phases:

### Shadow

Record every candidate and hypothetical execution.

### Internal simulator

Use broker quotes with modeled fills.

### Broker practice

Exercise real API order lifecycle and reconciliation.

### Limited live

Tiny risk to measure real slippage and operational behavior.

Paper duration is not the only criterion. Promotion should require a minimum number of independent trades and events, coverage across sessions/regimes, stable costs, and zero unresolved severe incidents.

## 11. Suggested promotion gates

Illustrative:

- at least 500 paper trades across approved setup families;
- at least 8–12 weeks of continuous operation;
- positive net expectancy after conservative costs;
- acceptable drawdown;
- no reliance on one pair or one week;
- calibrated confidence;
- stable results under worse slippage;
- all kill switches tested;
- all positions reconciled;
- no look-ahead findings in audit;
- risk approval.

Thresholds are configurable and should become stricter for scaled live mode.

## 12. Failure analysis

Every failed test or losing cluster is classified:

- strategy invalid;
- regime mismatch;
- execution cost;
- provider latency;
- data error;
- model drift;
- overfitting;
- implementation bug;
- random variance;
- risk-policy failure.

The platform should retain negative research results to avoid repeating them.

## 13. Reproducibility artifact

Every experiment stores:

- code commit;
- configuration;
- data snapshot IDs;
- feature versions;
- model versions;
- random seeds;
- start/end times;
- environment;
- metrics;
- generated reports;
- reviewer decision.
