# 04 — Technical and Order-Flow Engine

## 1. Purpose

The technical engine describes price location, structure, liquidity behavior, volatility, and flow. It emits features and setup evidence. It does not decide position size or send orders.

## 2. Price streams

The platform separates:

- executable broker bid;
- executable broker ask;
- broker midpoint;
- institutional reference or composite midpoint;
- CME futures trade and quote data;
- optional EBS or consolidated institutional FX reference;
- derived bars.

Bars must be reproducible from raw events and labeled by source. Research cannot silently mix broker bars with futures bars.

## 3. Market structure

The structure service identifies pivots using volatility-normalized thresholds. Outputs include:

- external swing highs/lows;
- internal pivots;
- higher-high/higher-low or lower-high/lower-low sequences;
- range boundaries;
- break of structure;
- potential change of character;
- displacement magnitude;
- retracement depth;
- trend strength;
- structural invalidation levels.

Multiple parameterizations may coexist, but each is versioned.

## 4. Supply and demand zones

Zone discovery combines:

- base formation;
- displacement from base;
- candle and range imbalance;
- departure velocity;
- volume or delta evidence;
- higher-timeframe confluence;
- event origin;
- freshness;
- retest quality.

### Zone status

- `CANDIDATE`
- `ACTIVE_FRESH`
- `ACTIVE_RETESTED`
- `WEAKENED`
- `BROKEN`
- `FLIPPED`
- `EXPIRED`

A zone can become a flip zone only through an explicit rule and cannot remain both demand and supply at the same time.

## 5. Liquidity map

The engine creates a time-versioned map of:

- equal highs and lows;
- previous-day/week extremes;
- session highs and lows;
- opening ranges;
- recent swing points;
- round-number bands;
- volume-profile nodes;
- low-volume gaps;
- unfilled imbalance zones;
- optional option-expiry levels.

Each pool has:

- price band;
- formation time;
- supporting observations;
- expected side of liquidity;
- strength;
- expiry;
- whether it has been swept;
- post-sweep response.

## 6. Volatility and spread regime

Technical signals are invalid without market-condition context.

Features:

- realized volatility across horizons;
- ATR and robust range estimates;
- spread percentile by pair and session;
- quote update rate;
- gap frequency;
- jump detection;
- volatility-of-volatility;
- liquidity proxy;
- event proximity.

Regimes may include:

- quiet range;
- normal trend;
- high-volatility trend;
- news shock;
- illiquid/wide spread;
- disorderly or degraded.

## 7. Order-flow reality in spot FX

Spot FX is decentralized and fragmented. Broker volume is local to that venue and often represents tick count, not complete traded volume. Therefore:

- broker tick volume may be used as a local activity feature;
- it must not be labeled global delta or institutional volume;
- futures or institutional CLOB data are preferred for delta, footprint, depth, and volume profile;
- all proxy mappings must be tested by pair and session.

## 8. Futures proxy map

Illustrative mappings:

- EUR/USD ↔ CME Euro FX futures;
- GBP/USD ↔ British Pound futures;
- AUD/USD ↔ Australian Dollar futures;
- NZD/USD ↔ New Zealand Dollar futures;
- USD/CAD ↔ Canadian Dollar futures with inverse orientation;
- USD/CHF ↔ Swiss Franc futures with inverse orientation;
- USD/JPY ↔ Japanese Yen futures with inverse orientation.

The mapping layer handles inverse quotes, contract rolls, session breaks, basis, and timestamp alignment.

## 9. Order-flow features

Where licensed data supports them:

- bid/ask traded volume;
- bar delta;
- cumulative delta;
- delta divergence;
- absorption;
- stacked imbalance;
- unfinished auction;
- point of control;
- value area;
- high- and low-volume nodes;
- trade-size anomalies;
- quote-depth changes;
- cancellation and replenishment patterns;
- pace of tape;
- VWAP and deviation bands.

No single feature is inherently bullish or bearish outside location and context.

## 10. Proxy confidence

Each order-flow observation receives a proxy-confidence score based on:

- contract liquidity;
- time-of-day overlap with spot;
- basis stability;
- quote orientation correctness;
- feed latency;
- missing data;
- contract-roll proximity;
- broker/reference divergence.

Low proxy confidence can downgrade or disable flow-dependent setups.

## 11. Technical confluence

Confluence is grouped by independent evidence families:

- location;
- structure;
- liquidity behavior;
- flow;
- volatility;
- timing;
- cross-asset.

Five indicators calculated from the same closing-price sequence do not count as five independent confirmations.

## 12. Technical setup outputs

A setup observation includes:

```text
pair
direction
setup_family
timeframe_stack
location_id
zone_id
liquidity_pool_id
structure_state
trigger_state
flow_state
volatility_regime
session_phase
invalidation_price
target_candidates
feature_quality
source_health
technical_confidence
```

## 13. Technical disqualifiers

- spread is abnormal;
- data gaps overlap setup formation;
- contract roll contaminates flow;
- location was identified after price reacted;
- zone is stale or overtested;
- entry is late relative to target;
- structure is ambiguous;
- flow proxy disagrees materially with executable market;
- expected stop is smaller than realistic noise and spread;
- target lies inside normal spread/slippage uncertainty;
- setup occurs in an unvalidated session.

## 14. Research agenda

- Compare algorithmic zone definitions with blinded human labels.
- Measure whether zone freshness predicts outcome.
- Quantify sweep excursion and reclaim timing by pair.
- Test futures delta lead/lag against spot execution prices.
- Determine whether VWAP features add value beyond structure and session.
- Validate each timeframe stack independently.
- Estimate how technical edge changes before and after macro events.
