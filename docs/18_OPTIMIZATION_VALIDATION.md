# 18 — Optimization and Validation

## Objective

The optimizer targets positive net expectancy while treating win rate, drawdown, profit factor, sample size and execution quality as separate constraints. Maximizing win rate alone is prohibited because it can favor tiny targets and hidden tail losses.

## Point-in-time combined replay

Version 0.3 can reconstruct fundamental state at each historical decision timestamp. `MacroObservation.available_at` is the governing field: observations, revisions, news and central-bank material that had not yet arrived are invisible. Future-dated seed snapshots are also excluded.

Import immutable history with:

```bash
python scripts/import_macro_history.py history.jsonl
```

Then replay the combined system:

```bash
python scripts/backtest_oanda.py --instrument EUR_USD --days 90
```

A diagnostic technical-only run remains available:

```bash
python scripts/backtest_oanda.py --instrument EUR_USD --days 90 --technical-only
```

Technical-only results must never be presented as validation of the combined fundamental strategy.

## Rolling validation

`python scripts/optimize_oanda.py` now performs rolling chronological train/validation windows inside a development period and then reports a final untouched holdout. Thresholds are selected only using earlier windows.

```bash
python scripts/optimize_oanda.py \
  --instrument EUR_USD \
  --days 180 \
  --train-size 80 \
  --validation-size 40 \
  --step 40
```

Multi-instrument validation uses the same rule independently per pair and aggregates only final holdout results:

```bash
python scripts/validate_oanda.py \
  --instruments EUR_USD,GBP_USD,USD_JPY \
  --days 180
```

## Execution-cost model

The live system records observed spread and realized slippage by UTC liquidity session. A learned session profile can only make the engine more selective; it can never increase the configured maximum spread. Backtests should also be stress-tested at wider fixed spreads until sufficiently dense historical tick/spread data exists for point-in-time session-cost replay.

## Promotion gate

Research performance does not itself authorize broader execution. The Practice evidence gate separately requires adequate decision and closed-trade samples, positive realized P/L, acceptable win rate/profit factor, bounded drawdown, low broker rejection/unknown rates and controlled median slippage.

```bash
forex-trader promotion
```

This is an evidence gate, not a promise of future profitability.

## Adoption rule

A configuration should not be promoted merely because it wins one backtest. Require, at minimum:

- positive untouched-holdout expectancy after realistic costs;
- meaningful sample size;
- acceptable maximum drawdown;
- stability across multiple rolling windows;
- stability across more than one instrument/regime;
- wider-spread and worse-fill sensitivity tests;
- point-in-time macro/news data with no future leakage;
- Practice execution results reasonably aligned with the modeled costs.
