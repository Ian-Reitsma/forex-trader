# v0.7.16 — Point-in-Time Central-Bank Stance Outcomes

## Purpose

v0.7.16 adds a research-only market-reaction layer on top of the source-backed central-bank stance evidence introduced in v0.7.15. It answers a narrow empirical question: after an official document became available, did the relevant FX pair subsequently move in the direction implied by the deterministic stance artifact?

It does **not** answer whether the stance extractor is semantically correct, whether the move was caused by the document, or whether the movement could have been captured as executable profit.

## Evidence chain

```text
first-party official document provenance
        ↓
explicit same-family current/prior lineage
        ↓
source-backed added/removed paragraph diff
        ↓
v0.7.15 deterministic stance artifact
        ↓
document available_at
        ↓
archived completed midpoint-candle opens
        ↓
complete 5/15/60/240-minute outcome panel
        ↓
research-only stance/outcome cohort evidence
```

No network request, broker order, runtime fundamental mutation, or strategy-policy mutation is required to assemble this artifact.

## Point-in-time baseline

Every comparable document event is anchored to the current document version's `available_at`, not the feed publication timestamp and not a retrospectively selected candle.

The baseline is the first **completed archived candle open at or after** document availability. The delay between `available_at` and that baseline is recorded as `baseline_delay_seconds` and must not exceed the configured maximum, 300 seconds by default.

An optional timezone-aware `as_of` instant restricts the dataset to evidence that would have matured by that point. Future candles are never silently used to complete an immature event.

## Complete-horizon panel

The default horizons are:

- 5 minutes;
- 15 minutes;
- 60 minutes;
- 240 minutes.

An event is observed only if every requested horizon is available. If one horizon is missing, the whole event is excluded with a reason such as `missing_horizon:240`.

This intentionally keeps one event denominator across horizons. It prevents a favorable short-horizon sample from using a different population than an unfavorable longer-horizon sample.

The requested horizon family is sorted and deduplicated deterministically before dataset identity is calculated.

## FX polarity

Raw pair return is always retained in basis points.

`stance_aligned_return_bps` applies both stance direction and pair-leg polarity so its sign has one invariant meaning:

> positive = the pair moved in the direction implied by the stance artifact for the policy currency.

Examples:

- hawkish USD in `USD_JPY`: pair rise is positive aligned return;
- hawkish USD in `EUR_USD`: pair decline is positive aligned return;
- dovish USD in `EUR_USD`: pair rise is positive aligned return.

The policy currency must be one leg of the analyzed `BASE_QUOTE` instrument or construction fails.

## Non-directional evidence is retained

Contradictory, neutral, ambiguous, and abstained stance artifacts are not discarded simply because they cannot produce a directional success metric.

Their raw FX return remains part of the dataset, while `stance_aligned_return_bps` is `None` for non-directional stance states. Cohort summaries therefore distinguish total sample size from directional sample size.

This protects research from quietly dropping difficult documents and reporting only directional cases.

## Explicit exclusions

Events that cannot be observed under the declared point-in-time contract are retained as `StanceOutcomeExclusion` records rather than disappearing from the denominator.

Examples include:

- `baseline_missing`;
- `baseline_delay_exceeded:<observed>><limit>`;
- `missing_horizon:<minutes>`.

Every exclusion retains current document version ID, availability timestamp, stance direction/disposition, evidence quality, and reason.

## Deterministic identities

Every observation has a SHA-256 identity bound to:

- explicit family ID;
- current document version ID;
- stance ruleset version;
- instrument;
- horizon;
- baseline timestamp/price;
- observation timestamp/price.

The dataset itself has a content identity bound to the research schema, family, policy currency, instrument, ruleset, complete horizon family, baseline-delay policy, optional `as_of`, ordered outcome IDs, and explicit exclusions.

Input ordering cannot change the resulting dataset ID.

## Price semantics

The artifact declares:

```text
completed_midpoint_candle_open_proxy_not_execution
```

That label is deliberate. These are informational market-reaction observations, not executable broker returns.

The layer does not model:

- bid/ask spread;
- order-book depth;
- entry latency;
- slippage;
- commissions or financing;
- market impact;
- stop/target geometry;
- trade management.

A positive stance-aligned return therefore cannot be described as strategy profit.

## Cohort summaries

Outcomes are summarized by:

- stance direction;
- evidence disposition;
- horizon.

Each summary reports:

- total sample size;
- directional sample size;
- mean evidence quality;
- mean and median raw return;
- mean and median stance-aligned return when directional;
- stance-aligned positive-return hit rate when directional.

These are descriptive research statistics. They are not calibrated probabilities, causal estimates, or promotion authority.

## Reproducible offline analysis

The analyzer reads the durable official-document SQLite lineage and an immutable candle archive:

```bash
python scripts/analyze_central_bank_stance_outcomes.py \
  <official-document-database> \
  <candle-archive.jsonl> \
  --family-id fed_fomc_statement \
  --instrument EUR_USD \
  --horizon-minutes 5,15,60,240 \
  --max-baseline-delay-seconds 300 \
  --output stance-outcomes.json
```

A historical research cutoff can be pinned with `--as-of <timezone-aware-ISO-8601>`.

## Authority boundary

Every outcome dataset is hard-coded:

```text
research_only = true
execution_authority = false
```

v0.7.16 does not change:

- deployable fundamental vectors;
- signal-fusion weights or gates;
- setup-family authority;
- risk sizing;
- OANDA Practice behavior;
- live-money authority.

## CI

The following new paths are explicit Ruff targets:

- `src/forex_trader/research/stance_outcomes.py`;
- `scripts/analyze_central_bank_stance_outcomes.py`;
- `tests/test_central_bank_stance_outcomes.py`;
- `tests/test_central_bank_stance_outcome_cli.py`.

The production/research module and analyzer are also direct strict-mypy targets.

Tests cover pair polarity, dovish/hawkish inversion, contradictory evidence retention, complete horizon panels, `as_of`, baseline-delay exclusions, deterministic identities, invalid instruments, duplicate candle timestamps, lineage drift, repository family ordering, archive lookup, and CLI parsing.

## What this release does not prove

Market reaction cannot be used as a substitute for semantic ground truth. A rule can be wrong about a document and still appear correlated with a price move by chance, by common information, or by another concurrent catalyst.

Likewise, even a semantically correct stance artifact that predicts midpoint direction does not establish executable after-cost expectancy.

The system therefore still lacks two independent evidence layers before runtime use can be considered:

1. **semantic validation** — a human-reviewed corpus bound to exact source document/version/diff IDs, measuring direction/disposition coverage, false-direction rate, contradiction handling, and per-dimension/institution/family errors;
2. **statistical validation** — chronological calibration/holdout evidence with uncertainty, minimum sample requirements, and simultaneous treatment of the declared horizon family.

Only after both survive independent evaluation should an execution-cost study be considered. Until then, central-bank stance remains research-only.