# v0.7.29 Forex Scalper Audit State

Date: 2026-08-09

## Executive result

The latest development-selected partial-runner policy did not survive sealed validation. The 71.875% development win rate is therefore rejected as an estimate of stable performance.

Development (2026-05-20 through 2026-08-07): 32 trades, 23 wins, 71.875% economic win rate, +0.111389R expectancy, profit factor 1.5627. Its one-sided 90% expectancy lower bound was already negative.

Untouched sealed validation (2026-04-15 through 2026-05-15, with 2026-04-01 through 2026-04-14 used only for causal shadow warmup): 6 trades, 2 wins, 4 losses, 33.3333% economic win rate, -0.411034R expectancy, -2.466201R total, profit factor 0.219673, max drawdown 3.056033R. The minimum proof floor of 20 trades was not met and every promotion gate failed.

At the runtime-default 0.15% risk per trade, the sealed sample returned -0.369624% total. The old active-exit-day metric was -0.073940% per active day across five active days. Across all 23 Monday-Friday dates in the sealed capital window, the corresponding arithmetic daily-return average is approximately -0.016074% per weekday. Full-period reporting is now implemented so future campaigns do not omit zero-trade weekdays from the primary daily-return denominator.

There is currently no defensible single "true win rate" or positive daily-profit estimate for the system. The sealed sample is small, but it is both negative and inconsistent with the attractive development result. The correct status is unproven edge, not 71.875% expected wins.

## Audit remediation merged after the failed policy was frozen

The following work improves research fidelity without retuning the failed April-May tape:

1. Full-period return reporting. Historical reports can distinguish active-exit-day return from return across every weekday in the declared test period.
2. Historical portfolio-risk replay. Research candidates can be replayed through the production `EnhancedRiskPolicy` with causal account state, open positions, realized/unrealized P/L, reserved risk, currency/gross exposure, macro-factor concentration, drawdown/loss streak and optional point-in-time correlation history.
3. Structured multi-candle zone research. A research-only detector classifies RBR, RBD, DBR and DBD bases and exposes arrival/departure ATR, base count, departure speed, body overlap, imbalance, freshness, penetration and age. It does not replace the Practice-authorized legacy zone detector.
4. Point-in-time release-surprise history. Historical consensus and actual releases can be joined only when consensus was strictly available before the actual. Normalization uses prior releases only, and unmatched/stale consensus is explicit. Official actual data is not used to manufacture market consensus.
5. Institutional-flow evidence research. Centralized snapshots can be decomposed into separately tagged delta, CVD change/divergence, absorption, depth imbalance, VWAP, POC and volume-expansion evidence. Provider-supplied directional pressure is retained only as a disagreement diagnostic and broker tick proxy remains ineligible as institutional flow.

## Remaining external data blockers

Historical market-consensus snapshots are still external. The code can ingest and causally assemble them, but the repository does not contain a licensed historical consensus archive.

Centralized institutional/futures flow is still external. The repository has adapters and research logic but does not contain entitled CME/EBS-equivalent historical depth/trade data. Do not substitute OANDA/broker tick counts for this requirement.

Centralized futures contract mapping also remains required: front/lead contract selection, roll boundaries, currency-pair orientation, price-scale mapping and source-specific quality checks must be frozen before using futures features in a sealed FX backtest.

## Next valid experiment

Do not optimize another technical-only runner on the April-May sealed window. It is now observed data and belongs to research history.

The next development campaign should be a new period and should test incremental components explicitly: legacy technical baseline; structured-zone metadata added; real point-in-time macro surprise added; real centralized flow added; and production portfolio-risk replay added. Each increment should be compared on the same causal opportunity stream with costs held constant.

Only after that development policy and its thresholds are frozen should a completely untouched time window be opened once. Promotion requires adequate sample size, positive expectancy after costs, profit factor above one, bounded drawdown, positive uncertainty-aware evidence, and stability across pairs/regimes. A high development win rate alone is not a promotion criterion.

## Practice status

No research-only module in this tranche receives Practice authority. OANDA remains Practice-only by architecture. A future authenticated campaign still requires read-only broker validation, reconciliation, a protected open/verify/close round trip, then a capped sustained Practice campaign. Historical profitability, even if later established, is not sufficient to bypass those gates.
