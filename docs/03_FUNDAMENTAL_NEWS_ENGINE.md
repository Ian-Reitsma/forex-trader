# 03 — Fundamental and News Intelligence Engine

## 1. Purpose

The fundamental engine converts economic releases, central-bank communications, policy expectations, macro data, and material news into currency-specific, horizon-specific evidence. It does not produce orders. It emits structured events and directional hypotheses with uncertainty.

## 2. Inputs

### Scheduled macro events

- policy-rate decisions;
- central-bank statements and minutes;
- inflation releases;
- employment and wage data;
- GDP and activity indicators;
- retail sales and consumption;
- PMIs and business surveys;
- trade balance and current account;
- fiscal announcements;
- bond auctions and debt-market events;
- official intervention or reserve announcements.

### Unscheduled events

- central-bank comments;
- government policy announcements;
- geopolitical developments;
- sanctions and tariffs;
- sovereign-credit actions;
- financial-stability events;
- emergency liquidity measures;
- natural disasters with material economic impact.

### Cross-asset context

- short- and long-term sovereign yields;
- rate-futures expectations;
- equity-index futures;
- volatility indexes;
- gold and oil;
- credit spreads;
- commodity prices relevant to CAD, AUD, and NZD;
- broad dollar measures;
- carry and funding conditions.

## 3. Event schema

Every event must include:

- provider event ID;
- canonical event type;
- country and affected currencies;
- scheduled or observed timestamp;
- provider-received timestamp;
- source-published timestamp when available;
- actual, consensus, previous, and revised values;
- units and seasonal-adjustment metadata;
- importance;
- source reliability;
- raw payload location;
- deduplication fingerprint;
- uncertainty flags;
- parser and model versions.

All timestamps are stored in UTC at the highest available precision.

## 4. Economic surprise model

A release should not be scored as simply `actual - consensus`. The engine calculates:

```text
raw_surprise        = actual - consensus
direction_adjusted  = raw_surprise × indicator_direction
normalized_surprise = direction_adjusted / historical_surprise_scale
revision_component  = revised_previous - previously_known_previous
```

The interpretation then considers:

- whether higher values strengthen or weaken the currency in the current policy regime;
- historical release volatility;
- revision significance;
- consensus dispersion when available;
- market positioning;
- the central bank’s current reaction function;
- time since release;
- cross-asset confirmation;
- whether the release is a component of a larger report.

For example, stronger employment can support a currency when inflation is elevated and policy is data-dependent, but may matter less if the central bank is focused on financial stability or if the surprise is driven by a low-quality component.

## 5. Central-bank policy model

Each central bank has a versioned policy state:

- current target rate or corridor;
- most recent decision;
- expected path from market pricing;
- inflation assessment;
- growth assessment;
- labor-market assessment;
- financial-stability concerns;
- balance-sheet policy;
- intervention risk;
- communication bias;
- confidence and freshness.

### Statement-delta analysis

The engine compares the new statement, minutes, or speech against the previous relevant document. It extracts:

- added and removed policy phrases;
- change in inflation concern;
- change in growth concern;
- change in confidence;
- explicit forward-guidance changes;
- balance-sheet changes;
- dissent or vote changes;
- conditionality;
- references to exchange-rate strength or weakness.

A language model may assist extraction, but the production output must conform to a typed schema and pass deterministic validation.

## 6. News-event interpretation

Generic sentiment is insufficient for FX. The same headline can affect currencies differently.

The pipeline:

1. source authentication and licensing check;
2. deduplication and story clustering;
3. entity and country extraction;
4. event-type classification;
5. affected-currency mapping;
6. directional impact by horizon;
7. novelty assessment;
8. credibility and source-weight assessment;
9. contradiction detection;
10. time decay;
11. cross-asset validation;
12. abstention when uncertainty is too high.

### Required output

```text
event_type
affected_currencies
direction_by_currency
impact_horizon
novelty
reliability
urgency
expected_volatility
confidence
supporting_facts
contradicting_facts
abstain_reason
```

The model never emits `BUY EURUSD`.

## 7. Currency fundamental vector

For each currency and horizon, the engine maintains components such as:

- policy-rate differential momentum;
- inflation surprise momentum;
- growth surprise momentum;
- labor surprise momentum;
- central-bank communication shift;
- yield confirmation;
- risk-on/risk-off sensitivity;
- commodity linkage;
- political/fiscal risk;
- event shock;
- positioning vulnerability.

These components are standardized and time-decayed. The vector is versioned and reconstructable for historical replay.

## 8. Pair mapping

Pair evidence is relative.

For EUR/USD:

- stronger euro evidence raises the pair score;
- stronger dollar evidence lowers the pair score;
- simultaneous positive EUR and USD events may cancel;
- the more immediate catalyst receives greater short-horizon weight;
- broad risk sentiment may affect both through different channels.

The system must explain which side of the pair drives the score.

## 9. Event-risk windows

Each event class has empirical windows:

- pre-event blackout;
- immediate release;
- spread normalization;
- initial impulse;
- first pullback;
- secondary repricing;
- decay.

Windows are estimated by pair, session, and provider latency. A single “avoid news for 30 minutes” rule is too crude.

## 10. Provider hierarchy

### Tier 1: direct official sources

Central-bank, statistics-agency, treasury, and government releases. Best for authority, sometimes harder for normalized delivery and latency.

### Tier 2: institutional licensed feeds

LSEG/Reuters or equivalent machine-readable news and analytics. Best target for low-latency production when budget permits.

### Tier 3: normalized economic API

Trading Economics or a comparable service for calendars, consensus, actuals, revisions, and streaming.

### Tier 4: broad news aggregators

Used for supplemental coverage, never as the sole source for high-impact automated trading.

### Social media

Research-only unless a verified official account, source authenticity, latency, and manipulation controls are solved. Unverified social sentiment must not directly authorize a trade.

## 11. LLM architecture

The recommended design is an ensemble:

- deterministic parsers for known calendar schemas;
- event-specific numerical surprise models;
- compact classifier for event type and currency mapping;
- financial-language model for statement differences;
- larger reasoning model only for adjudication of ambiguous, high-value cases;
- rule-based and schema validation;
- abstention and human review for uncertainty.

The larger model is not placed on the critical path for ordinary scheduled releases if latency would make the signal unusable.

## 12. Failure modes and controls

- Duplicate headline: cluster and suppress.
- Incorrect timestamp: quarantine event.
- Consensus missing: use event-specific fallback or abstain.
- Revision misread: preserve previously known value and new revision separately.
- Contradictory sources: reduce confidence or halt event trading.
- Provider delay: measure and tag; do not backfill as if real time.
- Hallucinated interpretation: schema-ground facts and reject unsupported claims.
- Source outage: degrade to blackout, not blind trading.
- Rumor: classify separately and cap influence.
- Already-priced news: novelty and market-response model reduce weight.

## 13. Research questions

- Which release families produce reliable continuation after spread normalization?
- Which pairs exhibit initial overreaction and failure?
- How quickly does each event’s predictive value decay?
- Does statement-delta scoring add value beyond rates-market reaction?
- Does cross-asset confirmation improve precision enough to justify latency?
- When does a neutral technical setup become tradable because of a catalyst?
- When should news act only as a risk gate rather than a directional signal?
