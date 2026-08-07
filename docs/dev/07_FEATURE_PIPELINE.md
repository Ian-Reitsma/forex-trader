# Feature Computation Pipeline

## 1. Feature contract

Every feature definition includes:

- name and version;
- input event types and fields;
- lookback and minimum sample;
- timestamp basis;
- late-data policy;
- null/unknown behavior;
- numeric units and orientation;
- expected range;
- calculation owner;
- validation fixtures;
- lineage output.

## 2. Technical features

Initial deterministic set:

- swing highs/lows with configurable left/right confirmation bars;
- break of structure and change of character;
- supply/demand zone anchors, departure strength, freshness, mitigations, and invalidation;
- equal highs/lows and prior session/day/week extremes;
- liquidity sweep and reclaim;
- displacement and fair-value-gap measurements;
- ATR and realized volatility across horizons;
- bid/ask spread level and percentile by pair/session;
- session phase and time-to-session boundary;
- VWAP and distance where valid volume is available;
- futures volume, delta, imbalance, profile, and divergence where licensed data supports them;
- spot/futures basis and proxy confidence.

Indicator features may be included as baselines but are not independent evidence merely because they have different names.

## 3. Zone algorithm requirements

A zone detector produces:

- anchor candle range;
- proximal and distal boundaries;
- direction;
- formation time and confirmation time;
- departure magnitude normalized by volatility;
- time spent at base;
- number and depth of revisits;
- freshness state;
- higher-timeframe overlap;
- invalidation time;
- algorithm version.

Human labels are used only for comparison and error analysis, not as hidden runtime inputs.

## 4. Fundamental features

- consensus surprise and historical z-score;
- previous-value revision effect;
- policy-rate path change;
- yield-curve and rate-futures repricing;
- inflation, labor, growth, and external-balance vectors;
- central-bank stance delta;
- event relevance and persistence estimate;
- cross-asset confirmation;
- source agreement;
- narrative novelty and contradiction;
- time decay by horizon.

## 5. Feature availability

A feature is published with `as_of` and `available_at`. Example: a one-minute candle ending at 12:01:00 UTC may be `as_of=12:01:00`, but if the watermark waits 500 ms, `available_at=12:01:00.500`. A decision at 12:01:00.200 cannot use it.

## 6. Batch and streaming parity

The same feature implementation SHOULD support incremental streaming and deterministic batch replay. Where separate implementations are unavoidable, parity tests compare outputs on golden datasets.

## 7. Missing data

Missing is not zero. Features emit an explicit availability state:

- `AVAILABLE`
- `WARMING_UP`
- `STALE`
- `GAPPED`
- `UNSUPPORTED`
- `DEGRADED`

Strategy policies declare which states they accept.

## 8. Feature snapshots

A strategy reads one immutable snapshot per evaluation. The snapshot references exact feature values, versions, source events, watermarks, and quality. It is stored before or atomically with the resulting decision.

## 9. Validation

- property tests for orientation and scale invariance;
- fixtures for session boundaries and daylight-saving changes;
- no-future tests for swing/zone confirmation;
- synthetic sweeps and structure shifts;
- futures contract roll cases;
- gap and late-event cases;
- comparison against independently calculated reference outputs.
