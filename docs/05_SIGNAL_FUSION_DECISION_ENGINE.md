# 05 — Signal Fusion and Decision Engine

## 1. Purpose

Signal fusion converts independent evidence into a trade hypothesis while preserving disagreement and uncertainty. It must not average contradictory signals into a falsely confident score.

## 2. Inputs

- currency fundamental vectors;
- pair technical setup;
- order-flow proxy;
- volatility regime;
- session phase;
- event proximity;
- execution-cost estimate;
- portfolio state;
- provider health;
- model calibration status.

## 3. Hierarchical decision model

### Level 1: hard gates

Examples:

- data freshness;
- source agreement;
- legal/market availability;
- broker health;
- session allowlist;
- event blackout;
- risk limits;
- minimum target distance;
- maximum spread;
- protective-order capability.

Failure means no trade, regardless of model score.

### Level 2: regime selection

Select the appropriate policy:

- range mean reversion;
- trend continuation;
- liquidity-sweep reversal;
- scheduled-news reaction;
- post-news continuation;
- event-failure reversal;
- no-trade disorderly regime.

### Level 3: evidence scoring

Within the selected policy, calculate component scores.

### Level 4: conflict resolution

Preserve signs and uncertainty. Fundamental/technical conflict may reject the trade or route to a separately validated countertrend policy.

### Level 5: expected-value and cost gate

Estimate:

```text
expected_net_value =
    p_target × expected_gain
  - p_stop   × expected_loss
  - spread
  - expected_slippage
  - commissions
  - adverse-selection allowance
  - operational uncertainty penalty
```

The estimate is uncertain and must be stress-tested.

### Level 6: risk authorization

Determine whether portfolio and account risk permit the order intent.

## 4. Example score structure

A research baseline, not a fixed production formula:

```text
technical_location      0–1
technical_confirmation  0–1
order_flow              -1–1
fundamental_alignment   -1–1
event_catalyst           0–1
session_quality          0–1
execution_quality        0–1
regime_fit               0–1
```

Weights are selected by regime and learned only through leakage-controlled research. A news-reaction model weights event surprise and execution normalization more heavily. A quiet-session zone model weights location and structure more heavily.

## 5. Currency-pair decomposition

The system should model currency strength separately before pair fusion.

```text
fundamental_pair_bias =
  horizon_weighted(base_currency_vector)
  - horizon_weighted(quote_currency_vector)
```

This prevents a model from confusing “USD strong” with “EUR/USD strong.”

## 6. Independence and double counting

A feature lineage graph identifies shared inputs. For example:

- RSI, MACD, and moving-average slope all derive from price;
- multiple news articles may be copies of one wire story;
- Treasury yields and rate-futures expectations may represent the same macro repricing;
- broker tick volume and quote update rate may overlap.

The fusion engine reduces weight for correlated evidence and clusters duplicated events.

## 7. Abstention

The decision engine must have a strong abstention policy. Valid abstention reasons include:

- evidence conflict;
- poor calibration;
- missing consensus;
- ambiguous statement;
- stale flow data;
- abnormal spread;
- unknown session behavior;
- low expected net reward;
- insufficient sample for this setup/regime.

An abstention is a correct operational outcome, not a model failure.

## 8. Explanations

The structured decision object is the source of truth. A narrative explanation is rendered afterward.

Required explanation fields:

- setup family;
- higher-timeframe context;
- exact location;
- liquidity event;
- technical trigger;
- fundamental driver;
- order-flow confirmation;
- spread and cost estimate;
- stop rationale;
- target rationale;
- risk allocation;
- known conflicts;
- invalidation;
- rejection reason if no trade.

## 9. Configuration versioning

Each decision references:

- strategy policy version;
- feature-set version;
- model versions;
- calibration version;
- risk-policy version;
- provider mapping;
- session-phase definition;
- source timestamps.

Historical decisions remain tied to the versions that produced them.

## 10. No-trade policies

The most important strategy may be no-trade.

No-trade states include:

- rollover and maintenance;
- unbounded news shock;
- stale or contradictory pricing;
- spread outside historical percentile;
- correlated portfolio overload;
- daily loss or drawdown breach;
- severe latency;
- model drift;
- broker reconciliation mismatch;
- unsupported currency event;
- public holiday or thin-liquidity condition.

## 11. Model roles

### Rules

Best for hard safety constraints, deterministic event parsing, and order-state logic.

### Statistical models

Best for calibrated probabilities, slippage, outcome likelihood, and regime classification.

### Machine learning

Best for nonlinear interactions after strict validation.

### Language models

Best for extracting structured meaning from speeches and news, clustering narratives, and generating explanations. They are not allowed to bypass hard gates or directly produce executable orders.

## 12. Performance attribution

Every closed trade decomposes outcome by:

- setup family;
- session;
- pair;
- fundamental alignment;
- event type;
- zone quality;
- flow confirmation;
- entry style;
- spread bucket;
- slippage bucket;
- risk size;
- exit reason;
- model version.

The system also measures rejected candidates to determine whether gates help or merely suppress opportunity.
