# Changelog

All notable changes to this repository are documented here.

## 0.6.0 — 2026-08-07

### Repository integration repair

- Reconciled the full validated v0.5 audit-remediation history with the later Practice-campaign commits after verifying that the hardened remediation tree had not actually reached `main`.
- Preserved both histories through an explicit merge-parent integration branch instead of force-resetting `main`.
- Restored the hardened structure-first engine, OANDA safety adapter, risk/session/calendar logic, research stack and remediation tests as the authoritative deployable tree.

### Practice evidence and optimization workflow

- Added an evidence-first Practice campaign runner with a configurable per-cycle new-order budget; remaining instruments continue in shadow after the budget is spent.
- Added broker-discovered all-currency-pair campaign support and lower-timeframe-aligned campaign cadence.
- Campaign evidence now records rejection codes, independent risk denials, provider errors, promotion state and the complete hardened broker-order status histogram.
- Generalized campaign fail-closed behavior from literal `UNKNOWN` only to every unresolved state: created, acknowledged, partially filled, unknown, reconciliation required, closing and emergency close.
- Added backward-compatible JSONL campaign analysis that classifies execution uncertainty, broker reject/cancel behavior, provider failures, missing fundamental data, market context, strategy formation, portfolio risk, unclassified abstentions and clean/selective operation.
- Analyzer rejects internally inconsistent evidence and refuses to interpret new/unknown rejection codes as a clean strategy result.
- Execution uncertainty always outranks strategy tuning; emergency-close evidence explicitly blocks further Practice-risk recommendations until dependent protection behavior is resolved.
- Added `scripts/analyze_campaign.py` and expanded `docs/25_PRACTICE_CAMPAIGN.md` with the read-only -> sync -> shadow -> broker-minimum round trip -> capped Practice -> diagnosis sequence.

### Validation

- Exact reconciled v0.6 head passes the complete Python 3.11 and 3.13 CI matrix.
- **222 tests pass** with **87.02% branch-aware coverage**; the repository fail-under remains **85%**.
- Package install, bytecode compile, `pip check`, secret-assignment scan and executed offline paper-order smoke pass on both Python versions.
- No authenticated OANDA Practice execution is claimed because the required Practice credentials are not available to this execution environment.

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
