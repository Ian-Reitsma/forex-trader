# 18 — Optimization and Validation

## Objective

The system is intended to improve net expectancy while keeping drawdown and catastrophic failure bounded. “Optimize for wins” and “optimize for profit” are not identical objectives: maximizing win rate alone can produce small wins and occasional large losses, while maximizing average return can permit an unacceptable loss rate. Every calibration therefore reports at least:

- trade count;
- win rate;
- expectancy in units of initial risk (`R`);
- profit factor;
- total `R`;
- maximum drawdown in `R`;
- timeout count;
- threshold and sample period.

## Version 0.2 selectivity changes

The live decision path is more selective than version 0.1:

- a liquidity sweep is required by default;
- directional displacement is required by default;
- the displacement candle must close in the directionally favorable part of its range;
- higher-timeframe trend separation is measured against higher-timeframe ATR;
- executable quote age is bounded relative to the completed signal candle;
- spread is capped at two pips by default;
- reward/risk is recomputed from the executable bid or ask and must remain at least 1.75;
- fundamental conflicts are rejected;
- the default combined-score threshold is 0.68;
- risk is reduced for lower-confidence candidates;
- duplicate signal candles and same-instrument position stacking are blocked.

These changes are hypotheses intended to improve precision and execution quality. They are not proof of improved profitability.

## Conservative outcome engine

`src/forex_trader/research/backtest.py` provides candle-barrier evaluation. If a stop and target are both touched in one candle, the stop is assumed to occur first. The replay waits until both M5 and H1 candles are complete, applies spread to entry and exit-side barriers, and marks timeouts to market between `-1R` and the candidate's target `R`. These rules deliberately avoid common look-ahead and optimistic intrabar assumptions.

## Walk-forward rule

Thresholds must be selected only on a chronological training fold. The selected threshold is then applied without modification to a later validation fold. A threshold is not adopted merely because training performance is high.

```bash
python scripts/optimize_oanda.py --instrument EUR_USD --minimum-trades 10
```

The script:

1. downloads recent OANDA Practice M5 and H1 candles;
2. replays signals using only candles available at each decision time;
3. uses a conservative spread assumption;
4. creates a chronological 70/30 split;
5. selects the score threshold on the first fold;
6. reports the untouched validation fold separately.

## Critical limitation

The OANDA optimization script is **technical-only**. It uses neutral fundamental inputs because the repository does not yet have historical point-in-time economic consensus, revisions, news and central-bank statements. Current macro data must never be injected backward into historical decisions. Combined strategy optimization is blocked until the historical fundamental event store exists.

## Adoption gate

A proposed configuration change should not be merged unless:

- validation expectancy is positive after spread and modeled costs;
- validation sample size is meaningful for the setup frequency;
- maximum drawdown is within the approved risk budget;
- performance is not dependent on one pair, one month or one news regime;
- the result survives wider-spread and worse-fill stress tests;
- a later untouched period remains available for final confirmation;
- paper execution confirms that modeled and realized costs are reasonably aligned.

## Next research priorities

1. Persist every economic forecast, actual release, revision and source timestamp.
2. Persist licensed news with receipt time and event clustering.
3. Add OANDA fill and close reconciliation to produce realized trade outcomes automatically.
4. Add transaction-stream restart recovery.
5. Add rolling regime labels and pair/session attribution.
6. Add cross-pair currency exposure and conversion-aware risk sizing.
7. Run multi-month walk-forward validation across majors before changing the default threshold.
