# 29 — Research Promotion Evidence Bundle

The research-promotion bundle answers one question: does one isolated setup family have enough reproducible evidence to justify further shadow-level study?

It does **not** grant OANDA Practice authority, change `config/system-policy-v0.7.json`, or replace broker/risk promotion controls. Its strongest possible disposition is `shadow_candidate`.

## Dispositions

The assessor returns exactly one of:

- `insufficient_evidence` — required evidence is absent or sample volume is not yet large enough;
- `rejected` — the evidence exists but fails an empirical or integrity requirement;
- `shadow_candidate` — every configured research requirement passed and the setup may be nominated for additional shadow comparison.

A shadow candidate remains non-executable unless the separate machine-readable authority manifest already permits execution.

## Setup isolation

Setup promotion evidence must be generated with an explicit setup filter:

```bash
python scripts/analyze_research_dataset.py \
  decision-evidence.jsonl \
  outcome-evidence.jsonl \
  --setup-family zone_continuation \
  --output zone-continuation-research.json
```

The analyzer records both the requested filter and the setup families actually observed. The promotion bundle refuses a report unless the observed family is exactly the requested family.

This prevents performance from `sweep_reclaim` or another setup family from subsidizing a weaker experimental setup that happens to share the same campaign policy fingerprint.

## Immutable dataset identity

The research analyzer computes SHA-256 over the decision-evidence file and outcome-evidence file and derives a combined immutable `dataset_id`.

The report records:

```text
decision_sha256
outcome_sha256
dataset_id = SHA256(decision_sha256 + ':' + outcome_sha256)
```

Ablation evidence must reference the same `dataset_id`. An ablation tied to another evidence corpus is a hard integrity failure, not a comparable experiment.

## Required evidence classes

The default promotion policy requires:

### Chronological sample volume

- at least 200 labeled trades for the isolated setup family;
- at least 40 validation predictions;
- at least 40 untouched-test trades;
- at least 20 untouched-test decisions admitted by the research EV gate.

Insufficient counts mean more data are required; they are not interpreted as a failed edge.

### Probability quality

- validation expected calibration error no greater than 0.08;
- validation Brier score no greater than 0.30.

These are research-policy defaults, not universal statistical constants. Changes to them must be versioned as policy changes rather than tuned after seeing a holdout result.

### Untouched holdout economics

The untouched test fold must have:

- positive expectancy in R;
- positive total R;
- maximum drawdown no greater than the configured R limit;
- positive expectancy and total R for the EV-eligible subset.

A profitable development/train period cannot satisfy these requirements.

### Data/runtime integrity

The decision-attempt error rate for the matched policy fingerprint must remain below the configured ceiling. A strategy cannot be promoted on a sample in which provider failures or evaluation exceptions selectively removed difficult market states.

### Controlled ablations

The initial required ablation set is:

```text
no_fundamentals
no_flow
no_session
no_zone_quality
no_retest
```

Missing ablation evidence yields `insufficient_evidence`.

The full policy is rejected if an ablated version materially outperforms it beyond the configured tolerance. This does not require every component to show a large positive contribution; it prevents knowingly carrying a component that demonstrably degrades untouched expectancy.

A future prospective multi-policy shadow runner should generate these ablations on the same immutable signal/evidence corpus. Until that evidence exists, the promotion bundle is expected to remain incomplete.

### Deterministic replay

At least two repeated research results must hash identically under the same experiment manifest. Different result hashes under one manifest are a hard reproducibility failure.

The assessor canonicalizes JSON before hashing so whitespace/key-order differences do not create false mismatches.

### Phase-D evidence when applicable

If a proposed promotion also changes entry or management policy, the exact proposed Phase-D policy must have:

- a confirmed paired untouched-holdout result;
- at least the configured minimum holdout scenarios;
- a strictly positive lower confidence bound for incremental R versus the baseline.

A strategy setup may be a shadow candidate without a Phase-D change. Once a Phase-D policy is proposed, that evidence becomes mandatory.

## Assessing a bundle

Example:

```bash
python scripts/assess_research_promotion.py \
  zone-continuation-research.json \
  decision-evidence.jsonl \
  --setup-family zone_continuation \
  --ablation-evidence zone-continuation-ablations.json \
  --replay-manifest experiment-manifest.json \
  --replay-result replay-1.json \
  --replay-result replay-2.json \
  --output zone-continuation-promotion.json
```

If an entry/management change is part of the proposal:

```bash
python scripts/assess_research_promotion.py \
  zone-continuation-research.json \
  decision-evidence.jsonl \
  --setup-family zone_continuation \
  --ablation-evidence zone-continuation-ablations.json \
  --replay-manifest experiment-manifest.json \
  --replay-result replay-1.json \
  --replay-result replay-2.json \
  --phase-d-report phase-d-report.json \
  --proposed-phase-d-policy limit-0.25r-structural
```

## Ablation evidence schema

The current bundle consumes explicit ablation evidence:

```json
{
  "ablations": [
    {
      "name": "no_fundamentals",
      "full_expectancy_r": "0.18",
      "ablated_expectancy_r": "0.05",
      "sample_size": 60,
      "dataset_id": "<immutable dataset id>"
    }
  ]
}
```

The schema is deliberately simple because the next research milestone is a prospective paired ablation collector. The promotion gate does not fabricate missing ablations from feature importance or from a single-policy backtest.

## Evidence digest

A successful or failed bundle receives a deterministic SHA-256 digest over its setup family, policy fingerprint, immutable dataset identity, calibration/holdout metrics, error counts, ablations, replay hashes and optional Phase-D evidence.

The digest allows later operator review to refer to the exact evidence package rather than a mutable collection of screenshots or aggregate P/L numbers.

## Relationship to existing Practice promotion

`domain/promotion.py` continues to protect the existing simulation/Practice execution path with broker-oriented requirements such as protected orders, ambiguous-write limits, slippage and drawdown.

The research bundle is intentionally separate. Future promotion policy can require a passing research bundle in addition to the broker/execution gate, but this release does not automatically combine them or elevate any setup family to Practice authority.

This separation prevents a research model from acquiring execution authority merely because its offline metrics look attractive.
