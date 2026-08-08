# v0.7.22 — Sealed Central-Bank Semantic Calibration / Holdout

## Purpose

v0.7.22 adds the missing train-of-thought-independent evaluation boundary between the v0.7.19 blinded human-annotation workflow and any future semantic acceptance criterion for the v0.7.15 central-bank stance extractor.

The release does **not** define a semantic pass threshold and does **not** claim the extractor has passed semantic validation. It creates the data-integrity workflow required to choose criteria on calibration evidence and then test those frozen criteria once on a chronologically later holdout.

The release remains research-only and has no execution authority.

## Verified release base

The actual GitHub `main` base for this tranche is merge commit `b9a98bf87809366c793b88e4074d2f440cadfac2`, which contains the v0.7.19 blinded annotation workflow.

The repository's runtime package identity had remained at `0.7.18` even though the v0.7.19 annotation workflow and documentation were merged. v0.7.22 normalizes the runtime/distribution identity directly to `0.7.22`; it does not invent or claim that runtime releases `0.7.20` or `0.7.21` were deployed.

## Fixed chronological split

The split policy is deliberately not configurable:

- source: one complete frozen v0.7.19 `AnnotationBatch`;
- minimum source sample: 3 comparable packets;
- ordering: existing deterministic packet order, which is chronological by current-document `available_at`, then current version ID;
- calibration: first `floor(2N / 3)` packets;
- holdout: every remaining packet;
- randomization: none;
- stratification: none;
- user-selectable split ratio: none;
- seed: none.

This prevents selecting a convenient split after inspecting human truth labels.

For example, a six-packet source batch becomes four calibration packets followed by two holdout packets.

## Immutable holdout manifest

`SemanticHoldoutManifest` binds:

- complete source annotation batch ID;
- explicit document family;
- annotation-policy version;
- frozen `as_of` cutoff;
- source packet denominator;
- fixed 2/3 split policy;
- exact ordered calibration packet IDs;
- exact ordered holdout packet IDs.

The manifest ID is a SHA-256 over the canonical payload. Changing the source batch, annotation policy, cutoff, packet membership, order, or split changes identity or fails validation.

The loader is schema-exact. Unknown fields are errors, so a manifest cannot silently carry model predictions, semantic scores, market outcomes, or other hidden research metadata.

## Partition batches

Calibration and holdout are each emitted as a normal existing v0.7.19 `AnnotationBatch`.

That design has two benefits:

1. the existing reviewer-submission and adjudication tools work without a second truth schema;
2. an operator can distribute only the partition that a reviewer is allowed to see.

The calibration and holdout batches have their own deterministic batch IDs derived from the same family, annotation policy, `as_of`, and exact subset packet IDs. The partition audit later binds those IDs back to the complete source batch and holdout manifest.

Create the split with:

```bash
python scripts/create_central_bank_semantic_holdout.py \
  blinded-annotation-batch.json \
  --manifest-output semantic-holdout-manifest.json \
  --calibration-output semantic-calibration-batch.json \
  --holdout-output semantic-holdout-batch.json
```

## What “sealed holdout” means

The holdout is a **process and data-access boundary around human truth labels and adjudication**, not encryption of public central-bank documents.

Official central-bank statements are public and the complete v0.7.19 source batch already contains every source document. Therefore secrecy of source text is neither realistic nor the statistical objective.

What must remain unavailable while semantic criteria are selected is the human-reviewed/adjudicated **holdout truth**. A sound operating process is:

1. freeze the complete source batch and v0.7.22 manifest;
2. distribute and annotate calibration packets;
3. finalize calibration labels;
4. use calibration labels only to choose and document semantic acceptance criteria;
5. freeze the criteria, extractor/ruleset version, annotation policy, and evaluation code;
6. only then collect/open/finalize holdout truth;
7. evaluate the frozen criteria once on holdout;
8. do not tune the same criterion again against that holdout.

The repository cannot prevent a person who has access to every artifact from intentionally violating the process. It makes the intended boundary explicit, reproducible, hash-bound, and fail-closed at supported file interfaces.

## Partition finalization

`finalize_semantic_partition` does not trust a subset in isolation.

Before accepting calibration or holdout labels it:

- materializes the official-document versions once, so generator/list/tuple callers receive identical behavior;
- rebuilds the complete v0.7.19 source annotation batch from the durable official-document repository;
- requires the rebuilt source batch to equal the supplied frozen source batch;
- reconstructs and validates the v0.7.22 holdout manifest;
- reconstructs the requested partition batch and requires exact equality;
- rejects submissions and adjudications from the other partition;
- requires at least two distinct pseudonymous reviewers per packet;
- requires exactly one adjudication per packet;
- requires the adjudicator to be independent from reviewers;
- requires adjudication to account for every supplied reviewer submission for the packet;
- verifies source document versions and exact diff ID before creating a semantic label;
- requires every packet in the selected partition to be finalized.

This prevents a calibration-only operation from silently becoming full-batch finalization and prevents cherry-picking a subset of reviews within a packet.

Finalize one partition with:

```bash
python scripts/finalize_central_bank_semantic_partition.py \
  <official-document-database> \
  blinded-annotation-batch.json \
  semantic-holdout-manifest.json \
  semantic-calibration-batch.json \
  calibration-reviewer-submissions.jsonl \
  calibration-adjudications.jsonl \
  --partition calibration \
  --labels-output calibration-semantic-labels.jsonl \
  --audit-output calibration-partition-audit.jsonl
```

The same command can later finalize `--partition holdout` with the holdout-specific batch/review/adjudication files.

## Existing full-batch behavior remains fail-closed

v0.7.22 does not weaken `finalize_annotation_batch` from v0.7.19.

Calling the original full-batch finalizer with only calibration evidence still fails because the complete frozen batch lacks reviewer/adjudication evidence for holdout packets. Partition finalization is a separate, explicitly partition-bound path with its own manifest and audit lineage.

## Partition audit

Every finalized partition label is paired with `PartitionFinalizationAudit`, which binds:

- holdout manifest ID;
- complete source batch ID;
- selected partition batch ID;
- partition name;
- packet ID;
- adjudication ID;
- semantic label ID;
- every source reviewer-submission ID;
- every pseudonymous reviewer ID;
- reviewer overall-agreement flag;
- reviewer dimension-agreement flag.

This keeps disagreement visible after adjudication and prevents a final semantic label from losing its partition provenance.

## Threshold boundary

v0.7.22 intentionally contains **no semantic acceptance threshold**.

It does not declare required direction accuracy, disposition accuracy, directional coverage, false-direction rate, contradiction recall, ambiguity recall, dimension accuracy, or cohort minimums.

Those values must not be selected by looking at the holdout. The next semantic-methodology step is to produce real calibration annotations, evaluate them with the existing v0.7.17 semantic evaluator, and predeclare a threshold policy using calibration evidence plus domain-risk judgment. Only after that policy is frozen should holdout truth be finalized and evaluated.

A passing semantic holdout would still be only one independent gate. Runtime integration would additionally require the existing market-reaction/statistical evidence and a later after-cost execution study.

## CI / software integrity

The dedicated `Annotation integrity` workflow directly checks on Python 3.11 and 3.13:

- Ruff on the annotation + semantic-holdout modules, operator scripts, and focused tests;
- strict mypy on annotation/holdout production and CLI code;
- focused v0.7.19 + v0.7.22 regression suites.

Repository-wide CI separately checks editable installation, compilation, dependencies, secret scanning, broader lint/typing, full branch-aware pytest coverage with the enforced floor, and protected simulation smoke.

CI demonstrates software/integrity behavior only. It does not establish human reviewer quality, semantic validity, causal FX response, executable expectancy, or profitability.

## Authority boundary

Every v0.7.22 holdout artifact remains:

```text
research_only = true
execution_authority = false
```

This release changes no runtime fundamental score, signal fusion rule, setup authority, risk limit, OANDA Practice behavior, broker-write path, or live-money authority.
