# 31 — Prospective Paired Ablations

The research-promotion bundle requires explicit evidence for:

```text
full
no_fundamentals
no_flow
no_session
no_zone_quality
no_retest
```

These cannot be inferred from feature importance and should not be produced by deleting labels after a trade outcome is known. The objective is prospective counterfactual evaluation: freeze one point-in-time market snapshot, run every predefined research variant against that same snapshot before future outcomes are known, retain every variant in the denominator, then compare matured outcomes on the same chronological holdout.

## Snapshot identity

`FrozenAblationSnapshot` binds each research evaluation group to:

- snapshot ID;
- instrument;
- timezone-aware signal time;
- policy fingerprint;
- SHA-256 of the canonical frozen input payload.

`ProspectiveAblationCollector` rejects any evaluator that changes snapshot ID, payload hash, policy fingerprint, instrument or signal time. This prevents variants from quietly fetching different candles, quotes or macro state and calling the result an ablation.

## Paired denominator

Every declared variant produces one `ProspectiveAblationDecision` row. Abstentions are rows. Evaluation exceptions are rows. A provider failure is captured as `evaluation_error` rather than removing the variant/snapshot from evidence.

After the horizon matures, each snapshot must have one `MaturedAblationOutcome` for every required variant. Missing or duplicate variants fail the paired assembler. Component expectancy is therefore computed on the exact same snapshot denominator as the full policy.

## Dataset identities

Two identities are intentionally separate:

1. **Primary dataset ID** — SHA-256 identity from the setup-isolated decision/outcome research corpus used by the v0.7.2 promotion report.
2. **Paired ablation artifact ID** — SHA-256 identity of the matured variant-outcome artifact itself.

Promotion-compatible ablation rows carry the primary dataset ID because they claim to measure components on that primary holdout. The output also records the paired artifact ID so the exact counterfactual evidence file remains independently identifiable.

The promotion bundle additionally checks that each ablation has the same untouched-test sample count and same full-policy baseline expectancy as the primary report. Supplying the correct primary dataset ID is therefore necessary but not sufficient to make mismatched evidence pass.

## Offline assembly

Once prospective variant outcomes have matured:

```bash
python scripts/assemble_paired_ablations.py \
  matured-ablation-outcomes.jsonl \
  --primary-dataset-id <dataset_id_from_research_report> \
  --output ablation-evidence.json
```

The command has no broker client, credential path or execution authority.

## What this release does not fake

This evidence layer deliberately does not claim that the six variants are already wired into the production decision engine. The next implementation step is a research-only feature-mask/evaluation surface that reruns the actual decision logic on a caller-supplied frozen snapshot:

- `no_fundamentals` must remove fundamental admissibility/confirmation, not merely blank a logged field;
- `no_flow` must remove flow-derived evidence/score effects and cannot turn missing institutional flow into synthetic confirmation;
- `no_session` must remove the session component while preserving all other point-in-time inputs;
- `no_zone_quality` must remove zone-quality contribution/gating without altering the underlying candles;
- `no_retest` must remove retest confirmation while preserving the original sweep/structure context.

Production defaults must remain unchanged, and the ablation surface must be inaccessible to broker-write authority. Until that actual-decision-path wiring exists, v0.7.2 correctly reports the required ablations as missing evidence.

## Promotion boundary

Even complete, favorable paired ablations only satisfy one research-promotion requirement. Calibration, untouched holdout economics, drawdown, provider integrity, deterministic replay and optional Phase-D evidence remain independent gates. A passing bundle can nominate a `shadow_candidate`; it cannot grant Practice authority.
