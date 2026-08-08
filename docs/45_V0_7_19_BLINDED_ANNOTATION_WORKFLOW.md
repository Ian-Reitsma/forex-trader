# v0.7.19 — Blinded Central-Bank Semantic Annotation Workflow

## Purpose

v0.7.19 operationalizes collection of the real human-reviewed semantic corpus required by v0.7.17.

It does **not** create or bundle real semantic labels. Tests use synthetic annotations only. A real corpus still has to be produced by independent human reviewers.

The workflow is deliberately isolated from the v0.7.15 extractor and the v0.7.16/v0.7.18 market-reaction layers so the human ground truth is not contaminated by the model prediction or subsequent price movement.

## What “blinded” means

Reviewers are **model- and outcome-blinded**, not source-anonymous.

A reviewer packet may show:

- institution;
- document family/type;
- currency;
- exact prior and current official URLs;
- official publication and availability timestamps;
- exact prior/current source-backed text;
- source text SHA-256 values;
- immutable prior/current version IDs;
- exact added/removed paragraph evidence and hashes;
- annotation-policy version.

A reviewer packet does **not** show:

- v0.7.15 stance direction or disposition;
- stance ruleset version;
- matched rule IDs;
- model/rule weights;
- evidence quality;
- model confidence or probability;
- v0.7.16 market returns;
- v0.7.18 statistical results;
- strategy decisions, trades, or P/L.

The JSON loader is schema-exact. Extra fields are rejected rather than ignored. A packet containing hidden fields such as `model_prediction`, `evidence_quality`, or `market_return_bps` therefore cannot enter the supported review workflow.

## Frozen, batch-complete export

Annotation export is not a hand-picked list of interesting cases.

For one explicit document family and one timezone-aware `as_of` cutoff, `build_blinded_annotation_batch` includes every comparable official-document version whose `available_at` is no later than the cutoff and whose explicit predecessor is present in the source corpus.

The manifest binds:

- family ID;
- annotation-policy version;
- frozen `as_of`;
- complete ordered packet-ID list;
- packet count.

The batch ID is a SHA-256 over that frozen manifest.

Changing the cutoff, policy, source document text, version lineage, source metadata, or diff changes packet/batch identity.

Export from the durable official-document database with:

```bash
python scripts/export_central_bank_annotation_batch.py \
  <official-document-database> \
  --family-id fed_fomc_statement \
  --annotation-policy-version central-bank-human-annotation-v1 \
  --as-of 2026-08-08T12:00:00+00:00 \
  --output blinded-annotation-batch.json
```

## Human review protocol

Each packet requires at least two independent reviewer submissions before adjudication.

Use stable pseudonymous reviewer IDs such as `reviewer-a17`, not names, email addresses, employee IDs, or other personal information.

Before submitting a review, each reviewer should independently inspect the source evidence under the same written annotation policy. Reviewers should not inspect:

- the stance extractor output;
- other reviewers' submissions;
- adjudication results;
- post-document FX returns;
- external analyst commentary intended to reveal how markets interpreted the document.

The supported truth vocabulary is inherited from v0.7.17.

Direction:

- `hawkish`
- `dovish`
- `neutral`
- `contradictory`

Disposition:

- `supported`
- `ambiguous`
- `contradictory`
- `abstained`

Optional dimension labels can be supplied for policy rate, inflation, labor, growth, balance sheet, FX, and financial stability.

A missing dimension means that dimension was not adjudicated; it should not be silently converted to neutral.

## Reviewer submissions

`ReviewerSubmission` binds:

- packet ID;
- annotation-policy version;
- pseudonymous reviewer ID;
- submission timestamp;
- overall direction/disposition;
- optional dimension labels.

Its SHA-256 identity changes if any review content or provenance changes.

Two submissions from the same reviewer ID do not satisfy the independence requirement.

## Adjudication

An adjudicator must be distinct from every source reviewer for that packet.

The adjudication record binds the exact sorted set of reviewer-submission IDs it considered. Finalization requires the adjudication to account for **every** reviewer submission supplied for that packet; selecting two favorable submissions while silently omitting a third is rejected.

The adjudicator may resolve disagreement to any truth state permitted by the written policy. The final semantic label records the adjudicated result, but the source reviewer disagreement is not erased.

## Disagreement audit

Finalization produces two separate outputs:

1. v0.7.17 `CentralBankSemanticLabel` records for semantic evaluation;
2. v0.7.19 finalization-audit records referencing the batch, packet, adjudication, semantic label, every reviewer submission, every reviewer ID, and agreement/disagreement flags.

The audit includes:

- `reviewer_overall_agreement`;
- `reviewer_dimension_agreement`.

The original reviewer-submission file remains the detailed record of what each reviewer said.

## Source-verified finalization

Finalization re-loads the official document family and reconstructs the exact frozen batch from the durable source database.

It fails closed if:

- the batch no longer matches source evidence;
- a packet is outside the frozen batch;
- a source version/predecessor is missing;
- a packet has fewer than two independent reviewers;
- a packet has zero or multiple adjudications;
- the adjudicator is one of the reviewers;
- adjudication predates a source review;
- adjudication omits one of the supplied reviewer submissions;
- a packet diff no longer reconstructs to its recorded `diff_id`;
- any packet in the frozen batch is left unfinished.

The finalizer materializes the source-version iterable once, so tuple/list/generator callers receive the same source-integrity behavior.

Finalize files with:

```bash
python scripts/finalize_central_bank_annotations.py \
  <official-document-database> \
  blinded-annotation-batch.json \
  reviewer-submissions.jsonl \
  adjudications.jsonl \
  --labels-output semantic-labels.jsonl \
  --audit-output annotation-audit.jsonl
```

Both outputs are required by the CLI.

## Annotation policy requirements

The policy version is part of packet, review, adjudication, label, and batch identity. A real study should write and freeze the policy before annotation begins.

At minimum the policy should define:

- what constitutes hawkish versus dovish change;
- how removal of prior language should be interpreted;
- treatment of negation;
- treatment of conditional language;
- treatment of uncertainty;
- treatment of mixed policy dimensions;
- when to use `ambiguous`;
- when to use `contradictory`;
- when to abstain;
- how optional dimension labels are assigned.

The policy must not be copied from the current extractor rules after reviewers see model output. The point of the human corpus is independent semantic ground truth.

## Real-corpus operating recommendation

For the first real corpus:

1. freeze one family and one `as_of`;
2. freeze the written annotation policy;
3. export one complete batch;
4. give the same source-only batch to at least two independent reviewers;
5. collect submissions without showing reviewers each other's answers;
6. let an independent adjudicator see the completed submissions and source packet;
7. finalize only after every packet is complete;
8. retain reviewer submissions and finalization audit outside model-training/evaluation code paths;
9. evaluate the adjudicated labels with v0.7.17;
10. keep any final semantic holdout sealed until acceptance criteria are predeclared.

## Authority boundary

Every artifact in this workflow is:

```text
research_only = true
execution_authority = false
```

v0.7.19 does not change runtime fundamental vectors, signal fusion, setup authority, risk sizing, OANDA Practice behavior, or live-money authority.

A completed human corpus is evidence infrastructure. It is not, by itself, a trading signal or profitability result.

## Next evidence step

After real annotations exist, the next useful quality layer is pre-adjudication inter-reviewer agreement and disagreement analysis by institution/document family/policy dimension. That analysis should be descriptive and source-bound; adjudication must not be treated as evidence that the reviewers originally agreed.

Only after a real semantic corpus passes predeclared v0.7.17 criteria **and** real v0.7.18 market-reaction panels survive the frozen statistical gate should an after-cost execution study be considered.