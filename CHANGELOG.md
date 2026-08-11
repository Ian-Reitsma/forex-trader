# Changelog

All notable changes to this repository are documented here.

## 0.7.40 — 2026-08-10

### Autonomous Practice runtime

- Added a dedicated continuous OANDA Practice runtime with pre/post-cycle broker reconciliation, broker-discovered/fundamental-eligible universe refresh, periodic free-official fundamental refresh/reload, bounded per-cycle order authority, evidence persistence and durable heartbeat state.
- `forex-trader autonomous` is the canonical all-eligible-pair daemon; OANDA `forex-trader run --execute` now uses the same durable orchestration and defaults to broker discovery/fundamental eligibility filtering, with `--configured-pairs` as an explicit opt-out. The API server remains observational.
- Added a durable singleton runner lease plus execution-time owner fencing so duplicate or stalled autonomous processes cannot silently create competing execution loops.
- Added `/v1/runtime` and runtime health/staleness inside `/v1/status`; the frontend no longer labels API connectivity itself as `STREAMING`.
- Enforced data-quality readiness at the broker-write boundary when the durable reconciliation/readiness contract is present.
- Corrected campaign lifecycle telemetry so a final `protected` order counts as both filled and protection-verified.
- Promotion accounting now excludes explicit `probe-` capability round trips and attributes separate OANDA daily financing to owned strategy trades.
- Expanded the read-only OANDA smoke report to expose whole-account open-position count, unrealized P/L and open positions.

### Safety boundary

- No strategy threshold, spread ceiling, slippage ceiling, risk fraction, exposure limit or live-money authority was relaxed. Execution remains OANDA Practice-only and unresolved broker state remains fail-closed.

## 0.7.1 — 2026-08-07

### Paired Phase-D counterfactual research

- Hardened pending limit/MIT/stop replay so a pending order is cancelled when the original setup invalidates or its structural target is reached before fill. Same-bar trigger plus stop/target ambiguity is treated conservatively instead of granting favorable execution ordering.
- Added spread-aware pending-entry replay and richer entry diagnostics for invalidation-before-fill, target-before-fill, ambiguous pre-fill paths, expired orders, opportunity cost and modeled entry adverse selection.
- Added paired Phase-D policies that combine market/limit/MIT/stop entries with structural-target or partial/runner management on the exact same signal/path denominator.
- Missed fills remain in the paired sample at 0R rather than disappearing; impossible post-fill management geometry is also retained and penalized at 0R instead of being silently excluded.
- Added chronological per-policy reports covering fill rate, R per original signal, R per fill, drawdown, missed-entry opportunity cost, adverse selection, ambiguity and invalid-management counts.
- Added deterministic paired-bootstrap confidence intervals for each variant's incremental R per original signal versus baseline.
- Added a research recommendation gate requiring enough paired scenarios, a positive lower confidence bound, minimum fill rate, acceptable drawdown and zero invalid management geometry.
- Added immutable JSONL candle-path datasets with duplicate instrument/time rejection and full combined entry+management maturity requirements.
- Added an offline development/untouched-holdout analyzer that has no broker client or credential path, selects at most one predefined Phase-D candidate on development data, and requires that same policy to confirm on untouched holdout data.
- Added `docs/28_PHASE_D_PAIRED_COUNTERFACTUALS.md` describing the paired-replay assumptions, selection-bias controls, confidence interval and Practice boundary.

### Release and validation

- Advanced authoritative runtime/distribution/API identity to `0.7.1`; campaign policy fingerprints therefore distinguish v0.7.1 evidence from v0.7.0 cohorts.
- The Phase-D implementation head passed the full Python 3.11/3.13 matrix with **329 tests passed** and **86.80% branch-aware coverage**, plus critical Ruff, strict mypy, dependency integrity, secret scanning and executed offline protected paper-order smoke.
- The exact `0.7.1` release head is revalidated before merge. Authenticated OANDA Practice success and profitability remain externally evidence-gated and are not inferred from software CI.
- No Practice or live-money authority is expanded by this release.

## 0.7.0 — 2026-08-07

### Phase 0 and A-D system architecture

- Added a machine-readable v0.7 authority manifest. OANDA remains fxTrade Practice-only; live-money execution is disabled. `sweep_reclaim:v1` is the only Practice-authorized setup family, while new families remain shadow/research gated.
- Added durable broker reconciliation-readiness at the write boundary, provider-health/readiness contracts, horizon-specific currency context, regime classification, independent confirmation categories/source identities, deterministic setup lifecycle, richer raw zone features, research order types and enhanced portfolio risk authorization.
- Added point-in-time release/news/central-bank intelligence contracts plus provider interfaces for economic calendars, official documents, licensed news, cross-assets and institutional flow. Missing licensed/real institutional data is represented as unavailable rather than fabricated from broker tick activity.
- Added event-time replay, experiment manifests, calibration primitives, outcome modeling, expected-net-R, ablation/attribution research, entry-style experiments and position-management intents while keeping unvalidated management out of Practice authority.

### Decision evidence and learning the edge

- Campaigns can now persist one point-in-time decision row per instrument attempt alongside the existing cycle aggregates. Detailed evidence captures immutable policy identity, setup/regime/session, independent confirmation categories and source IDs, candidate geometry, quote, risk/order state, raw feature evidence and provider errors.
- The permanent OANDA Practice validation workflow now uploads detailed shadow and Practice decision streams with the existing evidence artifact.
- Added a read-only OANDA outcome labeler that joins later historical candles to matured decisions using conservative stop-first OHLC semantics, captured decision-time spread and explicit slippage stress.
- Incomplete live paths are never written as timeouts: target/stop outcomes may resolve early, while a time-exit label requires the complete configured observation horizon.
- Added outcome-evidence identity checks, duplicate prevention and joins that fail on campaign, policy fingerprint, instrument or signal-time mismatch.
- Added hierarchical setup × regime × session calibration with optional instrument specificity and explicit sparse-cohort fallback.
- Added chronological train/validation/test separation and walk-forward probability evaluation using prior history only.
- Corrected the empirical outcome model to distinguish target hits, stop hits and time exits. Positive time exits no longer inflate target-hit probability, and timeout R contributes separately to expected value.
- Added a research-only EV gate requiring minimum sample size, bounded confidence width, validation calibration quality, positive after-cost EV and positive conservative lower-bound EV. It cannot authorize broker execution.
- Added dataset analysis that rejects mixed policy fingerprints and compares the untouched test fold before versus after EV eligibility.
- Added `docs/27_RESEARCH_EVIDENCE_AND_EV.md` with the complete capture → mature-label → calibration → untouched-fold EV workflow.

### Quality and validation

- Added incremental Ruff critical-error enforcement and strict mypy checks for the new deterministic Phase A-D/research contracts.
- Added Hypothesis/property and regression coverage around Phase A-D invariants, evidence serialization, campaign decision capture, chronological splitting, outcome labeling, three-outcome probability semantics, cohort fallback/calibration and conservative EV gating.
- Pre-release v0.7 research/evidence head passed the full Python 3.11/3.13 matrix with **319 tests passed** and **87.29% branch-aware coverage**, plus dependency/secret/lint/typing gates and the executed offline protected paper-order smoke.
- The authoritative runtime/distribution/API identity advances to `0.7.0`; the exact release-identity head is revalidated before merge.
- Authenticated OANDA Practice success and profitability remain externally evidence-gated and are not inferred from software CI.

## 0.6.4 — 2026-08-07

### CI and Practice readiness

- Repaired the v0.6.3 correlation snapshot regression test: `OpenPosition` is imported from the portfolio module, pair-level observation evidence is asserted on the correct object, and the expected provider call matches the configured 80-candle lookback.
- Advanced the authoritative runtime/distribution/API identity to `0.6.4`; campaign evidence continues to bind implementation version and exact build revision into the policy fingerprint.
- Replaced the obsolete branch/commit-message OANDA Practice workflow with a manual `workflow_dispatch` flow restricted to `main` and serialized by workflow concurrency.
- Added staged `read-only`, `round-trip` and `campaign` validation. Read-only requires only `OANDA_API_TOKEN` and may discover the authorized Practice account; broker-write stages additionally require explicit `OANDA_ACCOUNT_ID` and `confirm_practice_write=true`.
- The staged workflow performs the authenticated probe, broker transaction synchronization, one-cycle all-pair shadow campaign and analysis before any write stage. Campaign execution additionally requires a successful broker-minimum round trip, post-round-trip reconciliation, bounded campaign inputs and fresh cohort analysis/promotion output.
- Refactored the broker-minimum open/verify/close probe into a testable fail-closed helper. Once a known fill exists, the helper attempts to close that exact trade even when protection verification fails or raises, and treats failed/unverifiable closes as critical reconciliation conditions.
- Added Practice round-trip tests covering success, unprotected fills, protection exceptions, close failures, unknown-order reconciliation, unresolved unknowns, pre-existing-position refusal and blank-instrument rejection.
- Added workflow contract tests that enforce manual-only dispatch, serialized runs, shadow defaults, exact build identity, the staged validation sequence and absence of OANDA live-money hosts.
- Added an integrated token-only read-only contract test proving shadow config validation, authorized account discovery and transaction synchronization without an explicit account ID, while write-enabled configuration still requires an explicit account ID.
- Updated OANDA setup, Practice campaign and implementation-status documentation to match the staged operator path and credential boundary. No API token/account ID is written to source, evidence fingerprints or workflow artifacts.

### Validation

- Exact v0.6.4 code/test head passed the complete Python 3.11 and Python 3.13 CI matrix.
- **267 tests passed** with **87.40% branch-aware coverage**; repository fail-under remains **85%**.
- Fresh `forex-trader==0.6.4` installation, bytecode compilation, `pip check`, secret-assignment scan and executed offline paper-order smoke passed on both Python versions.
- Authenticated OANDA Practice success is intentionally not inferred from software CI; broker evidence remains externally credential/runtime-gated.

## 0.6.3 — 2026-08-07

### Evaluation-local completed-candle reuse

- Added a context-local completed-candle snapshot for one `FxTradingEngine.evaluate()` call.
- A larger completed-candle response can satisfy a later smaller request for the same instrument/granularity, reducing duplicate provider calls in the technical/correlation path.
- Quotes are never cached and the candle snapshot is discarded at the end of each top-level evaluation, so data cannot leak across decisions.
- Persisted FX trace policy/implementation labels were normalized to the current semantic strategy and runtime identity.
- The merge exposed a test-only collection regression on `main`; v0.6.4 repairs it and restores the authoritative post-merge CI gate before broker-facing validation.

## 0.6.2 — 2026-08-07

### Implementation identity

- Replaced conflicting package/build/API version declarations with `forex_trader.__version__` as the single runtime source and setuptools dynamic package metadata.
- FastAPI/OpenAPI now exposes the authoritative package version while preserving the existing `/health` response contract.
- Campaign policy cohorts now include `implementation.version`, preventing otherwise-identical strategy/risk configuration from silently pooling evidence across semantic software releases.
- Added optional exact source identity through `FOREX_BUILD_REVISION`; GitHub Actions falls back to `GITHUB_SHA` when an explicit revision is not provided.
- Exact build revision affects the campaign policy fingerprint but never includes credentials or account identifiers.
- Added `.env.example` documentation for immutable build revision and tests enforcing installed distribution/runtime/OpenAPI/campaign version agreement.

### Validation

- Exact v0.6.2 code/test head passed the complete Python 3.11 and Python 3.13 CI matrix with fresh dynamic package installation.
- **243 tests passed** with **87.29% branch-aware coverage**; repository fail-under remains **85%**.
- Install, bytecode compile, `pip check`, secret-assignment scan and executed offline paper-order smoke passed on both Python versions.
- Authenticated OANDA Practice execution remains externally credential-gated and is not claimed by this release.

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
