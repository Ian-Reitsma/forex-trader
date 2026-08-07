# 24 — Current Public Method Notes

## APPD terminology correction

As of the August 2026 public-site review, The Forex Scalpers checkout page explicitly expands APPD as **Algorithm Precision Price Delivery**. The repository's older research notes list several historically observed public expansions and session interpretations. Those historical references are retained only as provenance; they are not treated as current canonical terminology.

The current public wording still does **not** disclose a reproducible APPD algorithm, formula, rule set, parameterization, or executable decision graph. Therefore this project must not invent an `APPD()` calculation, represent a session template as the official algorithm, or give an undocumented APPD interpretation production authority.

Runtime behavior continues to be built only from concepts that can be independently defined and tested: supply/demand location, declared liquidity, pivot structure, sweeps and reclaim, confirmation/retest, session context, fundamental repricing, execution cost, and independent risk.

## FVG status

The public material describes the standard three-candle fair-value-gap/imbalance concept. The runtime repository now contains an explicit descriptive FVG detector with mitigation state and zone-overlap measurement. FVG remains a research/confluence feature rather than a mandatory trigger or independent source of risk authority until out-of-sample evidence shows incremental value after costs.

## Order-flow status

Spot-FX broker tick activity remains explicitly labeled as a low-confidence activity proxy. It is not treated as centralized executed bid/ask delta, footprint volume, or institutional order flow. A true futures/centralized order-flow integration remains a separate data-provider project and must use legitimately sourced data before it can affect production decisions.

## Evidence rule

Brand names and discretionary educational language are not executable specifications. A public concept receives production authority only after the repository can state exactly what is measured, when it is known, how it is timestamped, how it affects a decision, and how its incremental value was validated on untouched data.
