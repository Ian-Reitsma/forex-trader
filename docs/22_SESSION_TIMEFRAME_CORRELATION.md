# Session, Timeframe and Correlation Evidence

## Purpose

This specification closes three remaining research gaps identified during the public-method re-audit: daylight-saving-aware session timing, timeframe-policy ablation, and historical pair correlation. None of these components may be tuned on an untouched holdout.

## DST-aware sessions

London and New York are defined from their local market clocks using IANA time zones (`Europe/London` and `America/New_York`), not fixed UTC offsets. Tokyo uses `Asia/Tokyo`. The overlap is calculated from the local clocks on each timestamp, so the UTC boundaries move automatically through UK and US daylight-saving transitions, including the weeks in which the two jurisdictions change clocks on different dates.

Session labels are evidence features, not permission to widen execution limits. The learned spread/slippage policy retains the hard global ceiling and may only tighten it.

## Timeframe ablation

The H1/M5 baseline is no longer treated as canonical. Public TheForexScalpers examples describe higher-timeframe context such as H4/H1 and lower execution frames including M30/M15/M10, depending on the instrument and setup. The research grid therefore tests H4-M30, H4-M15, H4-M10, H1-M30, H1-M15, H1-M10, and the existing H1-M5 baseline.

A timeframe policy is eligible for promotion only if it is selected on training folds, remains stable over multiple chronological validation folds, and survives the final untouched holdout. A policy is never selected because it happens to maximize win rate on the final period.

## Correlation and covariance evidence

Currency-leg limits catch direct concentration but do not identify pairs that behave almost identically. The correlation module estimates aligned log-return correlations and creates absolute-correlation clusters. The intended portfolio use is to reduce aggregate risk when several positions occupy the same statistically correlated cluster.

Correlation estimates must be calculated separately by lookback and, where sample size permits, by regime/session. Missing or stale estimates do not create permission for more leverage. The first live integration should fail closed or fall back to the existing stricter currency-leg cap until the correlation sample is sufficient.

## Research-data prerequisite

The same admission policy used by all-pair historical research applies here. Correlation/timeframe results are not valid unless the pair has adequate executable bid/ask history and the combined strategy has adequate point-in-time macro history. Technical-only studies remain diagnostics rather than evidence for the combined system.
