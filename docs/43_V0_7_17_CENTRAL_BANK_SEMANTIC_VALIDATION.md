# v0.7.17 — Source-Bound Central-Bank Semantic Validation

## Purpose

v0.7.17 adds the missing semantic-validation contract for the research-only central-bank stance extractor introduced in v0.7.15.

The release does **not** claim that the extractor has passed semantic validation. The repository contains synthetic regression labels for software tests only; it does not contain a real adjudicated expert corpus.

The purpose is to make a future human-reviewed corpus immutable, source-bound, reproducible, and evaluable without substituting market reaction for linguistic ground truth.

## Why v0.7.16 is not semantic truth

v0.7.16 measures what an FX pair did after a source-backed document became available. That can test market association, but it cannot establish what the document actually meant.

Price may move because of:

- a different part of the same announcement;
- another simultaneous macro release;
- positioning or liquidity;
- prior expectations;
- cross-asset repricing;
- unrelated news;
- chance.

Accordingly, v0.7.17 never imports price outcomes into the semantic label.

## Label provenance

`CentralBankSemanticLabel` is an immutable human-review record bound to:

- explicit document family ID;
- exact previous version ID;
- exact current version ID;
- deterministic SHA-256 of the reconstructed v0.7.14 added/removed paragraph diff;
- annotation-policy version;
- source annotator IDs;
- adjudication state;
- adjudicator ID when adjudicated;
- timezone-aware labeling timestamp;
- overall truth direction and disposition;
- optional policy-dimension truth labels.

The label is hard-coded:

```text
source = human_review
research_only = true
execution_authority = false
```

The label ID is a SHA-256 over the immutable annotation payload. Editing the truth, provenance, reviewers, adjudication state, timestamp, or dimension labels changes the identity.

## Adjudication requirements

An adjudicated record requires at least two distinct source annotator IDs and a named adjudicator ID. IDs should be stable pseudonymous reviewer identifiers rather than personal information.

Unadjudicated records may exist in a corpus, but they are never silently scored as truth. The evaluation report retains their count and label IDs as explicit exclusions.

A corpus with no adjudicated record cannot produce a semantic evaluation report.

## Source reconstruction

Before scoring any adjudicated label, the evaluator loads the exact previous/current document versions from the durable official-document corpus and reconstructs their diff with the production v0.7.14 comparator.

Evaluation fails closed if:

- either document version is absent;
- the family differs from the label;
- previous/current are not an explicit predecessor pair;
- the reconstructed diff SHA does not equal the human label's `diff_id`;
- duplicate adjudicated truth exists for one diff;
- adjudicated labels mix annotation-policy versions.

This prevents a human label from drifting away from the source text it was intended to judge.

## Truth states

Overall and optional dimension labels reuse the explicit stance vocabulary:

Directions:

- `hawkish`;
- `dovish`;
- `neutral`;
- `contradictory`.

Dispositions:

- `supported`;
- `ambiguous`;
- `contradictory`;
- `abstained`.

Contradictory direction requires contradictory disposition. An abstained truth requires neutral direction.

Optional dimension truth can be supplied for:

- policy rate;
- inflation;
- labor;
- growth;
- balance sheet;
- FX;
- financial stability.

A missing dimension label means the human corpus did not adjudicate that dimension; it is not automatically treated as neutral.

## Evaluation metrics

`SemanticEvaluationReport` is descriptive and research-only. It reports:

- total label records;
- adjudicated label records;
- explicitly excluded unadjudicated records;
- exact overall direction accuracy;
- exact overall disposition accuracy;
- extractor abstention rate;
- directional-truth coverage;
- exact recall on directional human truth;
- number of directional calls;
- false-direction rate when the extractor makes a directional call;
- contradictory-truth recall;
- ambiguous-disposition recall;
- direction confusion matrix;
- per-dimension sample, prediction-presence, direction accuracy, and disposition accuracy;
- institution/document-type/family cohort metrics.

Abstentions are not dropped from the denominator. A false directional call against neutral, contradictory, or opposite-direction truth counts as a false directional call.

## Deterministic report identity

The report SHA binds:

- semantic-evaluation schema version;
- Forex Trader implementation version;
- stance ruleset version;
- annotation-policy version;
- corpus denominators;
- all reported metrics;
- confusion cells;
- dimension metrics;
- cohort metrics;
- evaluated adjudicated label IDs;
- explicitly excluded unadjudicated label IDs.

A future extractor code/ruleset or release change therefore produces a distinct evaluation artifact even against the same human corpus.

## Offline evaluator

A real human-reviewed JSONL corpus can be evaluated against the persisted official-document database with:

```bash
python scripts/evaluate_central_bank_stance_semantics.py \
  <official-document-database> \
  <human-label-corpus.jsonl> \
  --output semantic-evaluation.json
```

The command performs no network request and cannot submit an order.

## Minimal human-label JSON shape

The exact `label_id` should be generated through `CentralBankSemanticLabel.create(...)` so it binds the reconstructed source diff and complete annotation payload.

A serialized record contains fields such as:

```json
{
  "label_id": "<sha256>",
  "schema_version": "central-bank-semantic-label-v1",
  "research_only": true,
  "execution_authority": false,
  "source": "human_review",
  "diff_id": "<sha256>",
  "family_id": "fed_fomc_statement",
  "previous_version_id": "<version-id>",
  "current_version_id": "<version-id>",
  "annotation_policy_version": "central-bank-human-policy-v1",
  "annotator_ids": ["reviewer-a", "reviewer-b"],
  "adjudicated": true,
  "adjudicator_id": "adjudicator-1",
  "labeled_at": "2026-08-08T12:00:00+00:00",
  "direction": "hawkish",
  "disposition": "supported",
  "dimensions": []
}
```

No real annotation should be fabricated from the extractor's own output. Reviewers need the source-backed current/prior text/diff and a written annotation policy independent of the model prediction.

## Authority boundary

v0.7.17 does not change:

- runtime fundamental vectors;
- signal fusion;
- setup policy authority;
- risk sizing;
- OANDA Practice behavior;
- live-money authority.

A semantically favorable report would still be insufficient for runtime use. It would only satisfy one of the independent evidence requirements.

## Next required evidence

After a real human-reviewed corpus exists, the extractor must meet predeclared semantic acceptance criteria on an untouched or chronologically held-out set. Those criteria should include minimum corpus size and limits on false directional calls, not only aggregate accuracy.

Separately, v0.7.16 stance-aligned market outcomes require chronological uncertainty analysis with simultaneous treatment of the full 5/15/60/240-minute horizon family. Horizon selection must not be optimized after observing results.

Only if semantic and statistical validation both survive independent holdout should an after-cost execution study be considered. Until then, central-bank stance remains research-only.