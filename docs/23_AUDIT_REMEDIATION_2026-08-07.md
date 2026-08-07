# Audit remediation validation — 2026-08-07

This document records the implementation and validation state of the v0.5 audit-remediation branch. Git remains the source of truth; no Google Drive workflow is used.

## Software validation

The current remediation head passes the complete GitHub Actions matrix on Python 3.11 and Python 3.13. The CI path includes installation, bytecode compilation, dependency integrity, secret-assignment scanning, the full pytest suite with branch coverage enforcement, and an executed offline paper-trading smoke test.

Latest verified totals:

- **169 tests passed**;
- **85.94% branch-aware coverage**;
- repository coverage requirement remains **85%** and was not reduced;
- install, compile, dependency integrity and secret scan pass on both Python versions;
- executed offline simulation/paper-order smoke passes on both Python versions.

These are software and invariant tests. They are deliberately not described as evidence of trading profitability.

## Implemented audit remediations

The runtime now uses explicit supply/demand zones, declared liquidity levels, pivot-derived market structure, sweep/structure-shift/retest setup state, structural liquidity/zone targets, configurable researched lower/higher timeframe policies, completed-bar-close signal timestamps, session phases with DST-aware clocks, pair holiday blackouts, broker tick counts only as a clearly labeled low-confidence activity proxy, point-in-time fundamental replay, component-specific fundamental decay, release-revision handling, central-bank-specific parsing, scheduled macro blackouts, immutable macro/event storage, deterministic import IDs, broker-metadata pip sizing, gross hedged currency exposure, signed higher-timeframe correlation vetoes, margin-aware risk, latched daily marked-loss halts, account-scoped execution locks, expiring risk authorization, size-aware executable quotes, price bounds, deterministic-reject versus ambiguous-write classification, broker reconciliation, dependent stop/target verification and repair, and persistent execution uncertainty halts.

Research now exposes gap-through-stop losses, spread/slippage/delay stress, MAE/MFE and ambiguous-bar rates, uses one globally deployable threshold for multi-instrument validation rather than silently selecting a different production policy per pair, and includes fair-value-gap detection as a descriptive location/confluence feature rather than an automatically trusted signal.

The public-method record also now distinguishes current APPD branding from historical public interpretations. No undocumented APPD formula receives production authority.

## Practice validation attempt

The authenticated Practice sequence was deliberately gated behind a dedicated GitHub Actions workflow so broker writes cannot occur on ordinary code pushes.

A read-only Practice validation run was intentionally triggered after CI passed. The job stopped **before making an external OANDA request** because `OANDA_API_TOKEN` and `OANDA_ACCOUNT_ID` are not available as repository Actions secrets to this environment. The local execution environment also contains no project `.env` with those credentials. No token value was printed, copied or committed.

Accordingly, this branch does **not** claim that a real OANDA Practice order has been placed from this environment.

## Practice validation sequence once credentials are configured externally

1. Authenticated read-only OANDA fxPractice probe.
2. Broker currency-instrument discovery using real OANDA metadata.
3. Separately gated broker-minimum protected open/verify/close round trip.
4. Current-market shadow scan across the discovered FX universe.
5. Strategy-generated Practice entries only when actual runtime setups satisfy location, liquidity, structure, context, execution and risk gates.
6. Further strategy changes only from observed rejection/candidate/execution/outcome evidence; thresholds are not loosened merely to manufacture trade frequency.

The OANDA workflow remains Practice-only. Secret values must be configured outside chat and are never printed or committed.

## Deliberately unresolved rather than faked

- True centralized futures order-flow/footprint/delta data is not fabricated from spot tick counts.
- Automated licensed economic-calendar/news feeds are not substituted with scraped or unlicensed production data.
- Partial-profit/runners/trailing management is not hard-coded without comparative after-cost evidence.
- Historical midpoint candles are not presented as if they contained historical executable bid/ask depth.
- Passing CI is not presented as proof of positive expectancy.

The next meaningful evidence milestone is authenticated OANDA Practice behavior, followed by sustained multi-regime paper results and untouched historical validation.
