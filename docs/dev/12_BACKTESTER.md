# Point-in-Time Backtester and Replay Engine

## 1. Objective

The backtester executes the same domain policies used in shadow/paper mode against a controlled clock and point-in-time dataset. It is not a separate simplified strategy implementation.

## 2. Components

- dataset reader and manifest validator;
- deterministic replay clock;
- event scheduler with stable tie-breaking;
- in-process event bus;
- bar/feature workers;
- strategy and risk policies;
- simulated broker;
- portfolio ledger;
- metrics and attribution writer;
- reproducibility bundle generator.

## 3. Event scheduling

Events are ordered by `available_at`, then provider sequence, then stable event ID. Event time alone is insufficient. The scheduler supports market sessions, maintenance windows, daylight-saving transitions, and gaps.

## 4. Simulated broker

The broker simulator models:

- bid/ask execution;
- order activation conditions;
- latency distributions by workflow stage;
- spread by pair/session/event regime;
- slippage and adverse selection;
- market/limit/stop semantics;
- partial fills when supported by the chosen model;
- rejects and timeouts;
- protective orders;
- financing, commissions, and currency conversion;
- account margin and liquidation policy.

Models are calibrated from paper/live observations and versioned. Results are reported under base and stressed assumptions.

## 5. No-leakage controls

- query by `available_at`;
- use only pre-release calendar snapshots for expectations;
- preserve revisions as later events;
- do not use an unconfirmed swing or zone before confirmation time;
- use contract data available before the futures roll decision;
- fit scalers and models only inside training windows;
- keep the final holdout inaccessible to parameter selection;
- include provider receipt latency where known.

Automated leakage tests intentionally inject future records and assert rejection.

## 6. Experiment manifest

Each run records:

- git commit;
- configuration and policy hashes;
- dataset manifest/checksums;
- feature/model versions;
- random seeds;
- simulator/cost model versions;
- machine/container image;
- start/end and folds;
- command parameters;
- output checksums.

## 7. Evaluation design

Use anchored and rolling walk-forward windows, regime slices, event studies, and pair/session slices. Compare with simple baselines and ablations. Multiple-testing corrections and confidence intervals accompany headline performance.

## 8. Metrics

Trading metrics include net return, expectancy, profit factor, drawdown, tail loss, turnover, exposure, holding time, and risk-adjusted return. Prediction metrics include calibration, Brier score, log loss, ranking quality, and abstention coverage. Execution metrics include effective spread, slippage, fill rate, rejection, and latency. Stability metrics include parameter sensitivity and fold dispersion.

## 9. Replay parity

A captured shadow session can be replayed. The resulting candidate and risk-decision IDs may differ if IDs are not seeded, but semantic hashes, transitions, scores, and rejection codes MUST match.

## 10. Promotion output

The backtester produces a signed report package containing methods, datasets, costs, failures, uncertainty, ablations, and promotion recommendation. A profitable result alone cannot recommend promotion.
