# 02 — Strategy Specification

## 1. Strategy as a state machine

The bot does not jump from “signal” to “buy.” Every candidate moves through a deterministic lifecycle.

```text
OBSERVE
  → CONTEXT_ELIGIBLE
  → LOCATION_ARMED
  → CATALYST_OR_FLOW_DETECTED
  → CONFIRMATION_PENDING
  → TRADE_CANDIDATE
  → RISK_APPROVED
  → EXECUTION_APPROVED
  → ORDER_SUBMITTED
  → OPEN
  → MANAGING
  → CLOSED
  → ATTRIBUTED
```

At any stage, the candidate can transition to `REJECTED`, `EXPIRED`, `INVALIDATED`, or `SYSTEM_HALTED`.

## 2. Stage definitions

### OBSERVE

The pair is tracked, but no setup exists. Market data, calendars, and relevant news must be healthy.

### CONTEXT_ELIGIBLE

The pair passes:

- instrument and session allowlist;
- data freshness;
- spread and liquidity regime;
- macro/fundamental availability;
- no hard risk blackout;
- no portfolio exposure conflict.

### LOCATION_ARMED

Price is approaching a declared zone, liquidity pool, opening range, VWAP band, or another precomputed location. The system defines the exact invalidation and target candidates before waiting for a trigger.

### CATALYST_OR_FLOW_DETECTED

At least one of these occurs:

- liquidity sweep;
- scheduled release;
- unscheduled high-reliability news event;
- order-flow shift;
- volatility expansion;
- structure displacement;
- cross-asset confirmation.

### CONFIRMATION_PENDING

The system waits for the specific trigger required by the setup family. It cannot substitute another trigger after the fact unless the candidate is reclassified and logged.

### TRADE_CANDIDATE

A complete trade hypothesis exists:

- pair;
- direction;
- setup family;
- entry method and price constraints;
- structural stop;
- target path;
- maximum holding time;
- expected cost;
- evidence bundle;
- failure conditions.

### RISK_APPROVED

Portfolio risk, currency concentration, event risk, daily loss, drawdown, and correlation controls approve the candidate.

### EXECUTION_APPROVED

Current executable prices, spread, depth/proxy liquidity, latency, and broker state permit submission. The expected net reward still passes threshold.

### OPEN and MANAGING

The position is reconciled with broker truth. Management decisions follow the original archetype and may not be improvised by an explanation model.

## 3. Pair-relative directional model

Every currency receives a point-in-time directional score across horizons:

- immediate: seconds to minutes;
- session: current trading window;
- intraday: remainder of day;
- swing context: multi-day background, used only as context.

For pair `BASE/QUOTE`:

```text
pair_fundamental_score = base_currency_score - quote_currency_score
pair_technical_score   = technical_directional_evidence(BASE/QUOTE)
pair_flow_score        = order_flow_proxy(BASE/QUOTE)
```

A long trade requires the combined evidence to favor the base over the quote. A short trade requires the reverse.

## 4. Setup contract

Every setup family must define:

- context prerequisites;
- location prerequisites;
- trigger;
- confirmation;
- entry type;
- invalidation;
- target logic;
- timeout;
- trade-management policy;
- disqualifiers;
- required data sources;
- fallback behavior if one source fails;
- metrics used for validation.

No “miscellaneous” production trades are allowed.

## 5. Default setup contract: sweep and reclaim

### Context prerequisites

- price is at or near a quality zone or major session level;
- the targeted liquidity pool was declared before the sweep;
- no stale feed or abnormal broker spread;
- macro score is aligned, neutral, or explicitly classified as a countertrend exception;
- session phase is allowed.

### Trigger

Price trades beyond the pool by a normalized excursion and returns inside the pre-sweep boundary within the allowed interval.

### Confirmation

At least two independent categories:

1. price: displacement, reclaim close, structure shift, rejection;
2. flow: delta flip, absorption, CVD divergence, depth change;
3. fundamental/cross-asset: aligned event surprise, yield movement, risk proxy;
4. execution: spread normalization and stable quotes.

Two indicators derived from the same candle series do not count as independent categories.

### Entry

The preferred entry is the first valid pullback after reclaim. Market entry is permitted only when latency and slippage simulation show that waiting for a limit order materially reduces fill probability.

### Invalidation

Beyond sweep extreme or distal zone boundary plus a calibrated buffer. A close through the invalidation can trigger immediate exit if configured.

### Target

Primary target: next opposing liquidity or structure. Optional partial at a predefined R multiple only if validated. Remaining size may trail behind structure, not arbitrary price distance.

### Expiry

Candidate expires if:

- the pullback does not occur within the maximum bars/time;
- price reaches too much of the target before entry;
- spread widens beyond limit;
- a new high-impact event enters the protection window;
- the zone is invalidated.

## 6. News modes

### Blackout mode

No new positions within an event-specific window. Used when release latency, slippage, or data uncertainty dominates.

### Reaction mode

Wait for the actual release, normalize the surprise, let the first impulse and spread settle, then trade only a validated reaction setup.

### Continuation mode

Trade the first structured pullback after a release when the surprise, repricing, cross-asset response, and technical break agree.

### Failure mode

Trade against the initial move only when the initial reaction fails at a predeclared location and order flow confirms reversal.

The mode is selected by event type, provider latency, pair sensitivity, regime, and historical evidence.

## 7. Fundamental conflict policy

When technical and fundamental evidence conflict:

- no trade is the default;
- a technical scalp against the macro bias requires a separately validated countertrend setup;
- risk is reduced for short-horizon mean reversion;
- targets are closer;
- holding time is shorter;
- the trade cannot be relabeled as trend-following after entry.

## 8. Trade management

### Initial protection

A protective stop must be acknowledged by the broker or managed by a verified server-side equivalent. The system does not consider the position fully established until protection is confirmed.

### Scale-out

Scale-out rules are setup-specific. A research baseline may test:

- partial reduction near 1.5R–2R or first opposing node;
- stop reduction only after structure justifies it;
- runner toward the next higher-timeframe objective.

The platform must compare scale-out policies against full-exit policies after costs. Scaling is not assumed superior.

### Time stop

Scalps must have maximum duration or “failure to progress” logic. The threshold depends on setup, session, and volatility. Time exits prevent a small intended scalp from becoming an accidental swing trade.

### News protection

Open positions approaching a high-impact event follow an explicit policy:

- close;
- reduce;
- hold with unchanged risk;
- hold only if already risk-free by structural criteria.

The system never widens a stop because news is imminent.

## 9. Trade rejection reasons

Examples:

- `DATA_STALE`
- `PROVIDER_DISAGREEMENT`
- `SPREAD_TOO_WIDE`
- `SLIPPAGE_ESTIMATE_TOO_HIGH`
- `EVENT_BLACKOUT`
- `FUNDAMENTAL_CONFLICT`
- `ZONE_LOW_QUALITY`
- `NO_CONFIRMATION`
- `LATE_ENTRY`
- `INSUFFICIENT_NET_REWARD`
- `DAILY_LOSS_LIMIT`
- `CURRENCY_EXPOSURE_LIMIT`
- `CORRELATED_POSITION_CONFLICT`
- `BROKER_DEGRADED`
- `MODEL_UNCALIBRATED`
- `CONFIG_NOT_APPROVED`

Rejections are first-class research data. They are not discarded.

## 10. Confidence

Confidence is calibrated probability or expected-value quality, not a decorative percentage. It must be evaluated with reliability diagrams, Brier score or equivalent calibration metrics, and outcome bins. A 70% confidence label should historically correspond to approximately 70% occurrence of the defined event, within uncertainty.

The system should prefer a lower but calibrated confidence over a high uncalibrated score.
