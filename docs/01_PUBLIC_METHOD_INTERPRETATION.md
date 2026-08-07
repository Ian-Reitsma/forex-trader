# 01 — Public TheForexScalpers Method Interpretation

## 1. Scope and attribution

This document translates concepts described in publicly accessible TheForexScalpers articles and videos into a research specification. It does not reproduce a private course, paid book, proprietary indicator, or undisclosed formula. Any eventual implementation must be described as “inspired by public concepts,” not as an official or affiliated TheForexScalpers product.

## 2. Public concepts used by this framework

Across the public material, recurring concepts include:

- multi-timeframe supply and demand zones;
- higher-timeframe context before lower-timeframe execution;
- market structure and impulsive displacement;
- previous-day and session highs/lows as liquidity locations;
- liquidity sweeps or stop hunts followed by reclaim/reversal;
- confirmation entries after rejection or structure shift;
- order-flow confirmation, including delta, absorption, volume profile, point of control, and imbalances;
- VWAP and standard-deviation context;
- active session windows, especially London and New York transitions;
- stops beyond the structural invalidation area;
- targets at the next opposing zone, range extreme, or volume reference;
- scaling out and preserving a runner only when the move remains healthy;
- journaling and continuous review;
- strict daily-loss controls.

These are treated as hypotheses to validate, not universal truths.

## 3. Important APPD ambiguity

Public pages use “APPD” with inconsistent expansions. At least three public descriptions exist:

1. Accumulation, Manipulation, Distribution, Parabolic move.
2. Accumulation, Participation, Distribution, Decision.
3. A session-oriented sequence described as Asia accumulation, pre-London manipulation, pre-New York positioning, and New York deployment.

The platform must not hide this inconsistency. It will implement a versioned `SessionPhaseDefinition` configuration with:

- a unique definition ID;
- source and publication date;
- phase names;
- UTC and local-market time windows;
- expected liquidity behavior;
- allowed setup archetypes;
- risk multiplier;
- validation status by instrument and year.

No APPD definition becomes a production rule until it independently passes research.

## 4. Formal translation of core concepts

### 4.1 Supply and demand zone

A candidate demand zone is a bounded price area preceding an upward displacement. A candidate supply zone precedes a downward displacement.

Each zone receives measurable attributes:

- origin timeframe;
- start and end timestamps;
- proximal and distal boundaries;
- base-candle count;
- departure magnitude in ATR units;
- departure speed;
- imbalance or gap evidence;
- volume and delta context where available;
- number of prior retests;
- penetration depth on each retest;
- age;
- higher-timeframe alignment;
- proximity to liquidity pools;
- whether an important event created the departure.

A zone is not simply a manually drawn rectangle. Its quality score must be calculated from these attributes and calibrated against outcomes.

### 4.2 Freshness

A zone begins as fresh and loses quality as it is retested or deeply penetrated. “Freshness” is not binary. It is a decaying score that considers:

- number of touches;
- time spent inside the zone;
- depth of penetration;
- whether price departed with renewed displacement;
- whether market structure has since invalidated the original thesis.

### 4.3 Liquidity pool

A liquidity pool is an area where clustered stops or pending orders are plausible. Candidate pools include:

- equal or near-equal highs/lows;
- prior day high/low;
- prior week high/low;
- Asian session high/low;
- London or New York opening range extremes;
- recent swing points;
- round numbers;
- obvious range boundaries;
- high-volume and low-volume nodes;
- option-expiry references when licensed data is available.

The system records a pool as a hypothesis. It does not state that specific institutions “must” be positioned there.

### 4.4 Liquidity sweep

A sweep candidate requires:

1. price trades beyond a declared pool;
2. excursion distance remains within an instrument- and regime-specific bound;
3. price closes or trades back inside the prior structure within a maximum time;
4. spread and quote quality are acceptable;
5. reversal displacement or order-flow shift confirms the reclaim.

The setup quality increases when the sweep occurs at a higher-timeframe zone, during a validated session phase, with a fundamental catalyst or clear exhaustion.

### 4.5 Structure shift

A structure shift is a change in the sequence of meaningful pivots, not merely a one-tick break.

The detector must distinguish:

- continuation break of structure;
- potential change of character;
- internal microstructure break;
- external swing break;
- wick-only excursion;
- close-confirmed break;
- break with or without displacement.

Thresholds are normalized by volatility and spread.

### 4.6 Confirmation entry

Potential confirmation triggers include:

- rejection candle followed by break of its high/low;
- sweep, reclaim, and first pullback;
- displacement that closes beyond internal structure;
- delta divergence followed by order-flow flip;
- absorption at a zone and failed continuation;
- breakout with volume expansion followed by a successful retest;
- VWAP reclaim or rejection with aligned context.

Each trigger must be separately tagged so performance can be attributed by archetype.

### 4.7 Stop placement

The structural stop is placed beyond the zone or sweep extreme, plus a volatility- and spread-aware buffer. Position size is derived from the stop distance and risk budget. The system must never move the stop farther away merely to avoid realizing a loss.

### 4.8 Target selection

Targets are selected from market structure, not arbitrary profit amounts:

- nearest opposing zone;
- opposite side of the range;
- next high-volume node or point of control;
- prior session extreme;
- measured liquidity objective;
- volatility-adjusted maximum favorable excursion model.

A trade is rejected when the nearest credible target does not provide sufficient reward after estimated costs.

## 5. Multi-timeframe operating model

A default research hierarchy:

- Weekly/Daily: structural and macro location.
- 4H/1H: directional context, primary zones, major liquidity.
- 15M/5M: setup development and session structure.
- 1M/15S or tick: execution confirmation only when data quality supports it.

Lower timeframes may refine an entry but cannot overrule a hard higher-timeframe risk gate without an explicitly tested countertrend archetype.

## 6. Session model

The system creates session objects rather than hard-coding local clock strings:

- Asia;
- pre-London;
- London open;
- London continuation;
- pre-New York;
- scheduled U.S. release window;
- New York open;
- London fix;
- New York continuation;
- rollover and illiquid maintenance periods.

Each session object includes daylight-saving rules, expected liquidity, typical spread behavior, permitted pairs, and event proximity.

## 7. Public-formula-inspired setup families

### Sweep and reclaim reversal

Higher-timeframe zone + obvious liquidity pool + sweep + reclaim + confirmation + target to opposing structure.

### Zone continuation

Trend-aligned pullback into a fresh zone + controlled retracement + continuation order flow + structure-defined stop + next liquidity target.

### Breakout and retest

Compression near a meaningful boundary + catalyst or participation expansion + clean displacement + first valid retest + acceptable execution cost.

### Delta or flow divergence reversal

Price extends at a key institutional reference while futures delta or flow proxy fails to confirm + structure shift + first pullback.

### VWAP institutional repositioning

Price crosses or rejects futures VWAP with volume expansion, then validates on retest while macro and session context agree.

### Post-news continuation

High-impact release creates a statistically meaningful surprise + first impulse establishes direction + spread normalizes + pullback holds above/below a new structure + continuation entry.

### Post-news failure reversal

Initial move contradicts normalized surprise or fails at a higher-timeframe zone + liquidity sweep + reversal flow + price re-enters the pre-release range.

## 8. What is deliberately not assumed

The architecture does not assume:

- every wick is manipulation;
- every zone contains unfilled institutional orders;
- every liquidity sweep reverses;
- broker tick volume equals global FX volume;
- one session template works for every pair;
- a public discretionary concept can be automated without precise definitions;
- historical profitability proves future profitability.

Every discretionary phrase must be converted into a measurable feature, threshold, or labeled human-review field before implementation.
