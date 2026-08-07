# 28 — Paired Phase-D Counterfactual Research

Phase D asks a narrower question than strategy discovery: given the exact same trade signal and future market path, does a different entry or management policy improve expectancy after accounting for missed fills, adverse selection, ambiguity and drawdown?

This module is research-only. It has no broker client, no credential path and no Practice-authority mutation.

## Why paired replay is required

Independent backtests of market, limit and runner variants are easy to bias because each variant can end up with a different trade set. A limit entry may look excellent if missed trades simply disappear from the sample. A partial-profit policy may look strong if scenarios with impossible post-fill geometry are dropped. Both are selection bias.

The paired framework evaluates every predefined policy on the same ordered signal keys and future candle paths. Each original signal remains in the denominator:

- filled trades contribute their modeled realized R;
- unfilled pending orders contribute 0R and retain opportunity-cost diagnostics;
- invalid post-fill management geometry contributes 0R and is explicitly counted;
- ambiguous pending-entry bars are not given a favorable execution ordering.

The comparison therefore measures incremental R per original signal, not R per conveniently selected fill.

## Conservative pending-entry semantics

`research/order_types.py` now treats a pending entry as invalid when the original thesis has already ended.

For limit and market-if-touched pullback entries:

- the original stop/invalidation occurring before fill cancels the pending order;
- the original structural target occurring before fill records a missed opportunity rather than allowing a later fill;
- if the trigger and stop or target are all reachable inside the same OHLC bar, the path is marked `ambiguous_pre_fill_bar` and the fill is not granted;
- spread-adjusted executable extremes are used when spread is supplied.

Stop-entry variants also cancel if the original stop or target is reached before their trigger.

These rules deliberately favor false negatives over optimistic fill ordering.

## Policy definition

A `PhaseDPolicy` defines:

- entry style: market, limit, market-if-touched or stop;
- entry offset in original risk units;
- entry and exit slippage stress;
- maximum pending-entry horizon;
- maximum holding horizon;
- one deterministic management policy.

The first predefined comparison set is deliberately small:

```text
market-structural                 baseline
limit-0.25r-structural
mit-0.25r-structural
stop-0.25r-structural
market-half-1r-runner
limit-0.25r-half-1r-runner
```

This is not a parameter sweep. Adding dozens of offsets/management combinations without a nested validation design would increase multiple-testing risk and invite overfitting.

## Immutable path data

`research/path_dataset.py` consumes an explicit JSONL candle archive. Every row must identify an instrument and timestamp with OHLC values. Duplicate `(instrument, time)` rows are rejected rather than silently overwritten.

A decision becomes a Phase-D scenario only when the archive contains the complete combined entry plus management horizon. This is stricter than ordinary terminal-outcome labeling because all counterfactual policies must be mature on the same path before they can be compared.

Example candle row:

```json
{"instrument":"EUR_USD","time":"2026-08-07T14:00:00+00:00","open":"1.1000","high":"1.1010","low":"1.0995","close":"1.1007","volume":123,"complete":true}
```

The candle archive should itself be versioned/checksummed in the experiment manifest for serious research. Midpoint OHLC cannot be described as executable tick history; captured decision-time spread and explicit slippage stress remain separate assumptions.

## Comparison metrics

Each policy report includes:

- scenario count;
- fill count and fill rate;
- total R;
- average R per original signal;
- average R per fill;
- chronological maximum drawdown in R;
- average opportunity cost for missed entries;
- average modeled entry adverse selection;
- invalidated-before-fill count;
- target-before-fill count;
- ambiguous pre-fill count;
- expired-unfilled count;
- invalid management geometry count;
- ambiguous-path fraction.

Average R per original signal is the primary comparison metric because every policy sees the same denominator.

## Paired confidence interval

For each variant, the framework computes:

```text
delta_i = variant_R_i - baseline_R_i
```

for every original signal `i`.

A deterministic paired bootstrap resamples these signal-level deltas and reports a confidence interval for mean incremental R per signal. Pairing is essential: market and limit variants are exposed to the same underlying opportunity, so an unpaired comparison discards useful covariance and can exaggerate apparent differences.

The default research confidence level is 90% with a fixed seed. The seed is part of reproducibility, not a tuning parameter.

## Development and untouched holdout

Run:

```bash
python scripts/analyze_phase_d_paths.py \
  decision-evidence.jsonl \
  candle-archive.jsonl
```

The analyzer:

1. rejects mixed policy fingerprints;
2. builds only fully matured paired scenarios;
3. sorts them chronologically;
4. uses the development period to compare the predefined policy set;
5. selects at most one candidate policy;
6. evaluates only that selected policy versus baseline on the untouched holdout;
7. reports a confirmed research candidate only if the holdout independently passes.

Default minimums are 100 development scenarios and 30 untouched holdout scenarios. If the dataset cannot satisfy them, the analyzer stops and asks for more evidence rather than lowering the bar.

## Research recommendation gate

A variant is not eligible even on development data unless it satisfies all of the following:

- enough paired scenarios;
- positive lower confidence bound for incremental R per original signal;
- minimum fill rate;
- drawdown no worse than the configured ratio versus baseline;
- zero invalid management-geometry observations.

The untouched holdout must independently satisfy the same rule for the selected policy.

A confirmed result means only that one predefined Phase-D policy survived this paired development/holdout test. It does not prove a universal edge and does not authorize Practice execution.

## Practice boundary

No code in the Phase-D paired analyzer submits, modifies or closes an OANDA order. It does not read credentials. It does not alter `config/system-policy-v0.7.json`.

Before any future Phase-D policy could receive Practice authority, separate evidence must still establish:

- real broker mapping for the proposed order/management semantics;
- executable-price and slippage behavior;
- reconciliation/protection correctness;
- calibrated strategy expectancy on an immutable cohort;
- acceptable drawdown and portfolio interaction;
- reproducible ablations showing the Phase-D component adds value;
- sustained capped Practice evidence.

Until then, the deployable Practice path remains the existing protected structural execution behavior.
