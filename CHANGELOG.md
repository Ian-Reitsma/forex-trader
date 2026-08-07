# Changelog

All notable changes to this repository are documented here.

## 0.6.1 — 2026-08-07

### Evidence integrity and campaign efficiency

- Added deterministic, secret-free campaign policy fingerprints and run-level campaign IDs to every new campaign evidence row.
- Policy context records outcome-affecting strategy, risk, timeframe, correlation, adaptive-cost configuration and campaign execution policy without API tokens or account IDs.
- Campaign analysis refuses to combine multiple policy fingerprints unless the operator explicitly selects one with `--policy-fingerprint`.
- Evidence with one fingerprint but contradictory policy-context payloads is rejected rather than silently pooled.
- Pre-fingerprint JSONL remains supported as the `legacy` cohort.
- Practice-execution campaigns automatically pre-filter pairs that cannot currently meet the required fundamental-confidence gate before spending OANDA candle/pricing requests on guaranteed abstentions.
- Shadow campaigns continue to scan the full universe by default for fundamental-data coverage diagnostics; `--eligible-only` opts into the same preflight.
- Preflight exclusions are summarized in campaign metadata; no strategy/risk threshold is relaxed to increase trade frequency.
- Added cohort-isolation, policy-hash, point-in-time preflight, legacy-evidence and real-engine cohort-persistence tests.

### Validation

- Exact v0.6.1 code/test head passed the complete Python 3.11 and Python 3.13 CI matrix.
- **238 tests passed** with **87.27% branch-aware coverage**; repository fail-under remains **85%**.
- Install, bytecode compile, `pip check`, secret-assignment scan and executed offline paper-order smoke passed on both Python versions.
- Authenticated OANDA Practice execution remains externally credential-gated and is not claimed by this release.

## 0.6.0 — 2026-08-07

### Repository integration repair

- Reconciled the full validated v0.5 audit-remediation history with the later Practice-campaign commits after verifying that the hardened remediation tree had not actually reached `main`.
- Preserved both histories through an explicit merge-parent integration branch instead of force-resetting `main`.
- Restored the hardened structure-first engine, OANDA safety adapter, risk/session/calendar logic, research stack and remediation tests as the authoritative deployable tree.

### Practice evidence and optimization workflow

- Added an evidence-first Practice campaign runner with a configurable per-cycle new-order budget; remaining instruments continue in shadow after the budget is spent.
- Added broker-discovered all-currency-pair campaign support and lower-timeframe-aligned campaign cadence.
- Campaign evidence records rejection codes, independent risk denials, provider errors, promotion state and the complete hardened broker-order status histogram.
- Generalized campaign fail-closed behavior from literal `UNKNOWN` only to every unresolved state: created, acknowledged, partially filled, unknown, reconciliation required, closing and emergency close.
- Added backward-compatible JSONL campaign analysis for execution uncertainty, broker reject/cancel behavior, provider failures, missing fundamental data, market context, strategy formation, portfolio risk, unclassified abstentions and clean/selective operation.
- Analyzer rejects internally inconsistent evidence and refuses to interpret new/unknown rejection codes as a clean strategy result.
- Execution uncertainty always outranks strategy tuning; emergency-close evidence blocks further Practice-risk recommendations until dependent protection behavior is resolved.

### Validation

- Exact reconciled v0.6 head passed the complete Python 3.11 and 3.13 CI matrix.
- **222 tests passed** with **87.02% branch-aware coverage**; repository fail-under remained **85%**.
- Install, bytecode compile, `pip check`, secret-assignment scan and executed offline paper-order smoke passed on both Python versions.

## 0.5.0 — 2026-08-07

### Strategy fidelity

- Replaced the indicator-led live decision path with supply/demand location, declared liquidity, pivot-derived structure, sweep/reclaim, structure-shift and retest/hold state.
- Added structural invalidation stops and nearest credible opposing liquidity/zone targets instead of fixed 2R objectives.
- Expanded declared liquidity to 5-p.m.-New-York prior-day extremes, Sunday-5-p.m. prior-week extremes, finalized Asia highs/lows, finalized London/New York opening ranges, equal highs/lows, external swings and round-number references.
- Added source-time rules so a candle cannot sweep a level it created itself.
- Added fair-value-gap detection/mitigation as research/confluence evidence without automatic live authority.
- Removed the arbitrary fixed technical/fundamental score blend. Fundamentals operate as independent confidence/freshness/conflict gates; candidate score is explicitly non-probabilistic structure/location quality after cost penalty.

### Time, fundamentals, risk and execution

- Added deployable M5/M10/M15/M30 lower and H1/H4 higher timeframe policy and corrected completed-candle signal time to bar close.
- Added DST-aware sessions, country/ECB-TARGET2 holiday gates, 5-p.m.-New-York FX risk days and Sunday-5-p.m. trading weeks.
- Added immutable point-in-time macro observations, revision effects, component-specific decay, central-bank comparison and scheduled-event blackouts.
- Added gross currency exposure, concentration, margin reserve, signed-return correlation veto, account execution locks and expiring risk authorization.
- Added broker-metadata precision/margin handling, size-aware OANDA pricing, `priceBound`, deterministic reject vs ambiguous-write classification, reconciliation, protection verification/repair, emergency close and persistent uncertainty halts.
- OANDA remains Practice-only; no live-money endpoint exists.

### Research

- Added gap-through-stop semantics, spread/slippage/delay stress, MAE/MFE, ambiguous-bar reporting, rolling untouched holdouts, one globally deployable multi-pair threshold and research-only scale-out/runner comparison.

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
