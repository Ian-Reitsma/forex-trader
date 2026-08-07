# 36 — v0.7.10 Simultaneous Family-Wise Ablation Uncertainty

v0.7.10 upgrades component-ablation inference from five separate confidence intervals to one simultaneous family-wise confidence procedure. It is research-only and does not change Practice or live-money authority.

## Why this change is required

The prospective research program evaluates five component ablations at the same time:

```text
no_fundamentals
no_flow
no_session
no_zone_quality
no_retest
```

Treating five separate 90% intervals as though the family had 90% coverage overstates certainty. The tests are correlated because all five variants share the same frozen market snapshots and future paths, so an independent-test correction is also unnecessarily crude.

v0.7.10 uses the paired structure directly.

## Statistical unit and delta

For snapshot `i` and component `j`:

```text
delta[i,j] = full_realized_r[i] - ablated_realized_r[i,j]
```

Positive delta means the full policy outperformed the one-component ablation on that exact snapshot. Negative delta means removing the component did better.

## Synchronized paired bootstrap

Each bootstrap iteration:

1. Draws one vector of snapshot indices with replacement.
2. Applies that same index vector to all five component-delta series.
3. Computes the bootstrap mean delta for every component.
4. Centers each bootstrap mean on that component's observed mean.
5. Records the maximum absolute centered deviation across the five components.

The family-wise confidence quantile of those maximum deviations becomes one critical width `q`.

Every simultaneous interval is then:

```text
observed_mean_delta[j] - q
observed_mean_delta[j] + q
```

Using the same resampled snapshot indices across the whole family preserves the observed cross-component dependence. Using the maximum deviation controls the simultaneous family rather than five isolated marginals.

## Default configuration

Promotion-grade assembly defaults to:

```text
interval_scope = simultaneous_familywise
multiple_testing_method = paired_bootstrap_max_deviation_simultaneous
familywise_confidence = 0.90
family_size = 5
bootstrap_iterations = 5000
bootstrap_seed = 20260807
```

The prior individual paired percentile bootstrap remains available as a diagnostic API, but it is no longer sufficient for multi-component promotion.

## Artifact contract

The assembled artifact records, for every component:

- full and ablated expectancy R;
- paired mean component increment R;
- simultaneous lower and upper confidence bounds;
- paired wins, losses and ties;
- sample size and primary dataset ID;
- interval scope and multiple-testing method;
- family-wise confidence and family size;
- bootstrap iterations and seed.

The artifact-level uncertainty block repeats the common family configuration. All required component rows must agree on scope, method, confidence, family size, iteration count and seed.

## Promotion contract

The promotion policy requires:

```text
interval_scope == simultaneous_familywise
multiple_testing_method == paired_bootstrap_max_deviation_simultaneous
family_size == 5
familywise_confidence >= 0.90
bootstrap_iterations >= 5000
```

A coherent family configuration is required across all five components.

The existing material-harm tolerance remains `0.05R`, now interpreted with simultaneous bands:

```text
upper simultaneous bound < -0.05R
    -> REJECTED
       The component is confidently materially harmful under family-wise control.

lower simultaneous bound < -0.05R <= upper simultaneous bound
    -> INSUFFICIENT_EVIDENCE
       The family-wise evidence cannot yet rule out material harm.

lower simultaneous bound >= -0.05R
    -> component non-harm check passes
       Every other promotion gate still applies.
```

## Backward compatibility

Two older artifact classes remain readable:

1. mean-only component evidence;
2. v0.7.9 individual paired confidence intervals.

Neither can nominate a shadow candidate. Mean-only evidence lacks uncertainty. Individual intervals lack simultaneous multiple-testing control. They are classified as insufficient evidence rather than corrupted or rejected merely for being older.

## Assembly

```bash
python scripts/assemble_paired_ablations.py \
  matured-ablation-outcomes.jsonl \
  --primary-dataset-id <dataset_sha256> \
  --output paired-ablation-evidence.json \
  --familywise-confidence 0.90 \
  --bootstrap-iterations 5000 \
  --bootstrap-seed 20260807
```

The command remains offline/research-only and has no broker or credential path.

## What this release proves

Deterministic CI can prove the resampling contract, simultaneous-band construction, serialization, backward compatibility, family-configuration integrity and promotion state transitions. It cannot prove that any component has positive expectancy in real markets.

That requires a sufficiently large prospective capture/maturity corpus. The correct response to wide simultaneous bands is more evidence, not looser production gates.
