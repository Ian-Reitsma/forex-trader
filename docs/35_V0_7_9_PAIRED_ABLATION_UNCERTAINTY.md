# 35 — v0.7.9 Paired Ablation Uncertainty

v0.7.9 replaces raw-mean-only component promotion decisions with deterministic paired uncertainty. It is research-only and does not change Practice or live-money authority.

## Statistical unit

The statistical unit is one frozen prospective snapshot, not one independently sampled trade from each policy. For component `X`, the paired delta is:

```text
component_increment_r(snapshot) = full_realized_r(snapshot) - no_X_realized_r(snapshot)
```

Positive delta means the full policy performed better on that exact snapshot. Negative delta means removing the component performed better. Because the two outcomes share the same decision-time market snapshot and future path, the analysis bootstraps the paired delta vector rather than comparing two unrelated sample means.

## Deterministic paired bootstrap

`paired_ablation_uncertainty_evidence()` reuses the existing Phase-D `paired_bootstrap_mean_interval()` implementation. The default configuration is:

```text
confidence = 0.90
bootstrap_iterations = 2000
bootstrap_seed = 20260807
```

The artifact records the confidence level, iteration count, seed and method. Re-running the same matured artifact with the same configuration produces the same interval.

Each component row records:

- full-policy expectancy R;
- ablated-policy expectancy R;
- mean component increment R;
- lower/upper confidence bounds on the paired increment;
- paired wins, losses and ties;
- sample size and primary dataset ID;
- confidence level, bootstrap iterations and seed.

## Denominator integrity

Promotion does not trust a dataset ID string by itself. For every required ablation, the artifact must also match the primary untouched-test:

- dataset ID;
- sample count;
- full-policy expectancy R.

A mismatch is a hard integrity rejection. This prevents an unrelated paired corpus from being relabeled with the primary dataset ID and entering a promotion bundle.

## Promotion semantics

The existing material-harm tolerance remains `0.05R`, but it is now applied to the confidence interval of `full - ablated` rather than only the raw mean.

For one component:

```text
upper_CI < -0.05R
    -> REJECTED
       The component is confidently materially harmful.

lower_CI < -0.05R <= upper_CI
    -> INSUFFICIENT_EVIDENCE
       The data cannot rule out material harm.

lower_CI >= -0.05R
    -> component non-harm check passes
       Other promotion gates still apply.
```

This distinction matters. A noisy negative mean is not enough to reject a component; conversely, a noisy positive mean is not enough to certify it. Promotion requires at least 90% paired confidence and 1,000 bootstrap iterations by default.

## Legacy artifacts

Older mean-only ablation artifacts remain parseable so prior evidence is not destroyed. They have no uncertainty provenance and therefore produce `insufficient_evidence` rather than `shadow_candidate`.

## Assembly

After paired outcomes mature:

```bash
python scripts/assemble_paired_ablations.py \
  matured-ablation-outcomes.jsonl \
  --primary-dataset-id <dataset_sha256> \
  --output paired-ablation-evidence.json \
  --confidence 0.90 \
  --bootstrap-iterations 2000 \
  --bootstrap-seed 20260807
```

The command remains offline/research-only and has no broker or credential path.

## What this release proves

Deterministic CI can prove the statistical contract, serialization, backward compatibility, denominator checks and promotion state transitions. It cannot prove that any component has positive expectancy in real markets; that depends on accumulating a sufficiently large prospective capture/maturity corpus.

No production threshold should be loosened to accelerate that sample. The next useful evidence is real paired data, not more permissive gates.
