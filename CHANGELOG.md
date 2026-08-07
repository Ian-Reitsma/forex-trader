# Changelog

All notable changes to this repository are documented here.

## 0.5.0 — 2026-08-07

### Strategy fidelity

- Replaced the indicator-led live decision path with explicit supply/demand location, declared liquidity, pivot-derived structure, sweep/reclaim, structure-shift and retest/hold state.
- Added structural invalidation stops and nearest credible opposing liquidity/zone targets instead of constructing a fixed 2R objective.
- Expanded declared liquidity to 5-p.m.-New-York prior-day extremes, Sunday-5-p.m. prior-week extremes, finalized Asia highs/lows, finalized London/New York opening ranges, equal highs/lows, recent external swings and round-number references.
- Added source-time rules so a candle cannot sweep a level it created itself.
- Added fair-value-gap detection/mitigation as a research feature without granting it automatic live authority.
- Removed the arbitrary fixed technical/fundamental score blend. Fundamentals now operate as independent confidence/freshness/conflict gates; the candidate score is explicitly a non-probabilistic structure/location quality ranking after cost penalty.

### Time and market context

- Added deployable M5/M10/M15/M30 lower and H1/H4 higher timeframe policy matching the research grid.
- Corrected completed-candle signal time to bar close rather than OANDA bar-start timestamp.
- Added DST-aware session phases, London fix and rollover handling.
- Added country and ECB/TARGET2 holiday blackouts.
- Added 5-p.m.-New-York FX risk-day and Sunday-5-p.m. trading-week definitions.
- Expanded lower-timeframe runtime history to at least 48 clock-hours when necessary so M5/M10 day/session liquidity cannot be reconstructed from truncated data.

### Fundamentals and data integrity

- Added immutable point-in-time macro observations and deterministic import IDs.
- Added component-specific freshness/decay, release-revision effects and central-bank statement comparison.
- Added scheduled high-impact event persistence and hard blackouts.
- Preserved spot tick counts as a clearly labeled low-confidence activity proxy rather than representing them as centralized executed order flow.

### Risk and execution

- Added gross currency-leg exposure, single-currency concentration, margin reserve and signed recent-return correlation vetoes.
- Aligned realized daily P/L aggregation and the persistent marked-loss latch to the 5-p.m.-New-York FX trading day.
- Added account-scoped execution locks and expiring risk authorization.
- Added broker-metadata pip/display/unit/margin handling.
- Added size-aware OANDA Practice pricing buckets and worst-price `priceBound`.
- Distinguished deterministic broker rejection from ambiguous writes.
- Added ambiguous-write reconciliation, dependent stop/target verification, protection repair, emergency-close handling and persistent execution-uncertainty halts.
- OANDA remains Practice-only; there is no live-money endpoint.

### Research

- Added gap-through-stop semantics, spread/slippage/delay stress, MAE/MFE and ambiguous-bar reporting.
- Added chronological rolling validation with untouched final holdouts.
- Changed multi-instrument validation to select one globally deployable threshold rather than pair-specific thresholds.
- Updated all OANDA historical research scripts to use the same configured timeframe policy as runtime.
- Added research-only management comparison for the structural single-target baseline versus a 50%-at-1R / breakeven-runner hypothesis, with a CI equivalence guard for the baseline replay.

### Validation

- Current verified remediation state: 197 tests passing on Python 3.11 and 3.13, 87.29% branch-aware coverage with the 85% fail-under gate enforced.
- Package install, compile, dependency integrity, secret assignment scan and executed offline paper-order smoke pass on both CI Python versions.
- A gated authenticated OANDA Practice probe was attempted but stopped before external access because credentials are not available in this environment. No real OANDA Practice trade is claimed.

## 0.4.0 — 2026-08-07

- Expanded OANDA instrument metadata support and dynamic currency-pair universe discovery.
- Added broker transaction synchronization and reconciliation scaffolding.
- Added point-in-time macro history and research validation utilities.
- Added session/cost research and portfolio exposure scaffolding.
- Strengthened CI and secret checks.

## 0.3.0 — 2026-08-06

- Added OANDA Practice paper-trading MVP, SQLite decision persistence, CLI/API, independent risk authorization and simulation provider.
- Added unit/integration test suite and GitHub Actions CI.

## 0.2.0 — 2026-08-06

- Added initial executable vertical slice around technical assessment, fundamentals, fusion, risk and paper execution.

## 0.1.0 — 2026-08-06

- Added documentation-first system architecture and implementation framework.
