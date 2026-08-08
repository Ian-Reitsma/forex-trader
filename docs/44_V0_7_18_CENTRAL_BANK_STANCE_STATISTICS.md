# v0.7.18 — Chronological Family-Wise Central-Bank Stance Statistics

## Purpose

v0.7.18 adds the independent statistical-validation policy for the point-in-time central-bank market-reaction panels introduced in v0.7.16.

This release does **not** claim that real central-bank stance outcomes have passed the gate. The repository contains synthetic regression panels used to verify the statistical machinery only.

It also does not replace v0.7.17 semantic validation. A price response cannot prove that the stance interpretation was linguistically correct.

## Predeclared policy

The statistical policy is fixed in code before real evaluation:

- horizon family: **5, 15, 60, 240 minutes**;
- primary horizon: **60 minutes**;
- chronological split: first two-thirds calibration, final one-third untouched holdout;
- minimum directional events: **24**;
- minimum calibration events: **16**;
- minimum holdout events: **8**;
- minimum observed-event fraction: **80%**;
- simultaneous family-wise confidence: **90%**;
- joint event-level bootstrap iterations: **5,000**;
- deterministic bootstrap seed: `20260808` for calibration and `20260809` for holdout;
- source baseline-delay policy: **300 seconds**;
- source dataset must have an explicit timezone-aware frozen `as_of` cutoff.

There is no CLI switch for choosing another primary horizon, narrowing the horizon family, changing the confidence level, changing bootstrap iterations, changing the split ratio, or tuning baseline delay after looking at results.

## Why the full horizon family is simultaneous

The 5/15/60/240-minute outcomes for one document are correlated observations from the same event. Treating each horizon as an independent experiment would understate multiplicity and create an obvious path to selecting whichever horizon happened to look best.

Each bootstrap iteration therefore samples event IDs once and applies that same resample vector to all four horizons. For each iteration the validator calculates the absolute deviation of every bootstrap horizon mean from its observed mean and retains the maximum deviation across the family.

The 90th percentile of those maximum deviations becomes one simultaneous critical width. Every horizon band uses that width.

This preserves cross-horizon dependence and provides family-wise mean intervals for the complete predeclared family.

## Chronological calibration and holdout

Directional document events are sorted by document `available_at` and immutable event identity.

The first two-thirds form calibration. The final one-third form untouched holdout. With the minimum 24 directional events, this produces exactly 16 calibration events and 8 holdout events.

The holdout is not used to choose the primary horizon or statistical policy. The primary horizon is fixed at 60 minutes before the holdout is examined.

## Source-data integrity

The validator accepts only a v0.7.16 research-only outcome dataset that preserves:

- the complete 5/15/60/240-minute horizon family;
- `completed_midpoint_candle_open_proxy_not_execution` price semantics;
- an explicit frozen `as_of` cutoff;
- the fixed 300-second maximum baseline delay;
- complete event-panel denominators;
- explicit source exclusions.

The direct Python validator enforces these conditions itself. They are not merely CLI conventions.

The report identity includes the source dataset ID, frozen `as_of`, baseline-delay policy, implementation version, stance ruleset version, complete policy, event denominators, chronological split identities, all four simultaneous bands, disposition, and reasons.

## Coverage gate

At least 80% of all considered document events must have complete v0.7.16 outcome panels.

Missing baselines or missing horizons remain source exclusions. A dataset cannot earn an informational-candidate state by dropping too many difficult or immature events even if the remaining directional sample is large.

Non-directional stance events are retained in `events_observed` and reported separately. They are not forced into directional returns.

## Disposition

The strongest possible state is deliberately named:

```text
informational_signal_candidate
```

It is granted only when all fixed sample/coverage requirements pass and the **untouched 60-minute holdout simultaneous lower mean bound is above zero**.

If the untouched 60-minute simultaneous upper mean bound is below zero, the result is:

```text
rejected
```

Otherwise the result is:

```text
insufficient_evidence
```

Strong 5-, 15-, or 240-minute results cannot override a negative or unresolved 60-minute primary result. Secondary horizons are diagnostic only under this policy.

## What a positive result means

A positive simultaneous stance-aligned midpoint return at the primary horizon means that, in the evaluated point-in-time sample, the relevant FX pair tended to move in the direction implied by the research-only stance artifact.

It does **not** establish:

- semantic correctness;
- causal attribution to the central-bank document;
- bid/ask executability;
- after-cost expectancy;
- stop/target quality;
- entry latency robustness;
- market-impact robustness;
- strategy profitability.

The v0.7.16 source price remains a completed midpoint-candle open proxy, not an executable quote.

## Offline validation

The frozen file-based validator is:

```bash
python scripts/validate_central_bank_stance_statistics.py \
  <official-document-database> \
  <candle-archive.jsonl> \
  --family-id fed_fomc_statement \
  --instrument EUR_USD \
  --as-of 2026-08-08T12:00:00+00:00 \
  --output stance-statistical-validation.json
```

`--as-of` is required so the research sample cannot move implicitly as newer candles become available.

## Independent evidence gates

Central-bank stance still has two separate evidence requirements:

1. **semantic validation** — v0.7.17 against a real independently human-reviewed/adjudicated corpus tied to exact source diffs;
2. **statistical validation** — v0.7.18 against real point-in-time outcome panels using the frozen policy in this document.

Passing one cannot compensate for failing or missing the other.

Only if both survive independent holdout evaluation should an after-cost execution study be designed. That later study would need actual executable quotes/costs, not the midpoint outcome proxy used here.

## Authority boundary

Every v0.7.18 report remains:

```text
research_only = true
execution_authority = false
```

v0.7.18 does not change:

- deployable fundamental vectors;
- signal fusion;
- setup-family authority;
- risk sizing;
- OANDA Practice execution;
- live-money authority.

No stance-based trading authority is created by this release.