# Phase 0 and A-D Implementation

This document records the implementation boundary introduced after the Drive architecture audit. The system remains Practice/paper-only. No live-money OANDA host, credential path or automatic promotion mechanism is introduced.

## Phase 0 — specification lock

`config/system-policy-v0.7.json` is the machine-readable authority manifest. Sweep/reclaim v1 is the only setup family with Practice authority. Zone continuation and breakout/retest are shadow-only. Post-news continuation is shadow-only and requires institutional flow. Post-news failure is research-only. Broker tick activity is never relabeled as institutional order flow.

## Phase A — information integrity

The runtime now has explicit provider-health, data-quality and trading-readiness contracts. OANDA Practice execution has a durable reconciliation-readiness latch: broker writes through the configured runtime fail closed until `forex-trader sync` successfully catches up the authoritative broker transaction stream in the same database.

Point-in-time event contracts distinguish pre-release consensus from release actuals and revisions. News documents retain publication and receipt time, authority and deterministic fingerprints. Syndicated copies are clustered rather than counted as independent evidence. Central-bank extraction has a strict structured evidence contract with stance dimensions, caveats, source spans, confidence, disposition and model/prompt version.

Currency context is represented by horizon-specific vectors (`immediate`, `session`, `intraday`, `background`) with separate policy, inflation, labor, growth, risk-sensitivity, external-balance, terms-of-trade and positioning/repricing components. External provider protocols are defined for economic calendars, official documents, news, cross assets and institutional order flow. Providers that do not exist or are not licensed are represented as unavailable rather than fabricated.

## Phase B — strategy intelligence

Independent confirmation categories are explicit: price, flow, fundamental, cross-asset and execution. The configured runtime requires at least two independent categories and two source identities after the existing structural/fundamental/cost gates pass.

A regime model distinguishes trend, range, transition, pre-event, post-event impulse, post-event normalized, disorderly and rollover states. A versioned policy registry maps regime to setup families and authority. Only the existing sweep/reclaim implementation can reach Practice execution.

Setup lifecycle is now modeled as deterministic persisted transitions from observing through context, location, catalyst, confirmation and candidate production, with explicit expired/rejected/invalidated terminal states. Raw zone research features now expose departure speed, imbalance, flow alignment, retests, penetration, age, time in zone, renewed displacement, higher-timeframe alignment, liquidity proximity and event origin without inventing new production weights.

## Phase C — learning the edge

Research now includes an event scheduler ordered by `available_at`, provider sequence and stable event ID; content-addressed experiment manifests; Brier/ECE calibration reports; a regularized empirical outcome model; explicit expected-net-R after spread/slippage/commission/financing/adverse-selection/operational uncertainty; ablation comparisons; and structured expectancy attribution.

These components deliberately keep `TradeCandidate.score` as a quality ranking. Probability and expected-value labels require an independently calibrated outcome model.

## Phase D — execution expectancy

The internal order contract now has explicit order type, time-in-force, limit/trigger price and expiry fields so market, limit, stop and market-if-touched research can share one internal plan without silently approximating unsupported broker semantics.

A deterministic position-management policy can emit HOLD, REDUCE, MOVE_PROTECTION or CLOSE based on protection state, original structure, maximum holding time, failure to progress, high-impact event proximity and validated break-even progress. The policy never widens the original stop. It is not automatically granted Practice authority until broker trade-state mapping and after-cost out-of-sample validation are complete.

Risk authorization now carries candidate identity, environment, approved direction/size, entry range, stop, stressed maximum loss, required protection, portfolio snapshot identity, risk-policy version, consumed limits and an integrity digest. Additional controls cover trailing drawdown, loss streak observation, reserved/pending risk, gap-stress loss and holiday/rollover vetoes.

## External dependencies that remain external

The repository now has the correct contracts for real economic-calendar, official-document, licensed news, cross-asset and institutional-flow providers. It does not invent credentials, scrape unlicensed sources or claim a CME/Trading Economics connection that is not configured. Connecting those providers remains a deployment/data-license task.

## Validation rule

Profit is not inferred from unit tests, simulation or a short Practice session. Strategy changes must be evaluated through point-in-time replay, costs, untouched holdout data, calibration, drawdown, ablations and capped Practice evidence. A one-session profit cannot justify loosening a gate.
