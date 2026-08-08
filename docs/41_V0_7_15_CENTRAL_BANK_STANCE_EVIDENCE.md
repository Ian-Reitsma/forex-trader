# v0.7.15 — Source-Backed Central-Bank Stance Evidence

## Purpose

v0.7.15 adds a deterministic, research-only stance evidence layer on top of the v0.7.14 current-vs-prior official document diff. It is an auditable baseline for evaluating central-bank language changes; it is not a production NLP model, a calibrated probability system, or an execution signal.

## Evidence chain

Every stance span is downstream of the source-provenance chain established in v0.7.11-v0.7.14:

```text
first-party feed discovery
        ↓
official document body + raw SHA-256
        ↓
explicit same-document-family version lineage
        ↓
current-vs-prior added/removed paragraph evidence
        ↓
paragraph SHA-256 + exact rule match offsets
        ↓
research-only stance evidence
```

The extractor does not analyze arbitrary whole-document text. Its only input is `OfficialDocumentDiff`, whose added/removed paragraphs are already bound to explicit predecessor/current version IDs.

## Versioned deterministic rules

The initial ruleset is `central-bank-statement-rules-v1`.

Rules are deliberately conservative and dimension-specific:

- policy rate;
- inflation;
- labor;
- growth;
- balance sheet;
- FX;
- financial stability.

Each rule carries an explicit phrase, direction, dimension, rule ID, and transparent weight. The v1 lexicon favors abstention over broad semantic guessing.

A matched span retains:

- added/removed side;
- paragraph index;
- exact paragraph text and SHA-256;
- rule ID and matched phrase;
- exact character offsets;
- policy dimension;
- lexical direction;
- effective direction after change-side semantics;
- weight;
- negation flag;
- uncertainty flag;
- conditional flag;
- deterministic evidence ID.

Offset/hash/evidence-ID tampering fails validation.

## Added versus removed language

The system models the change in policy language, not just the phrase itself.

For example:

- adding a hawkish phrase contributes hawkish evidence;
- removing that hawkish phrase contributes dovish change evidence;
- adding a dovish phrase contributes dovish evidence;
- removing that dovish phrase contributes hawkish change evidence.

This avoids treating disappearance of restrictive/easing language as neutral simply because the phrase is absent from the new document.

## Negation, uncertainty, and conditional language

A phrase match is not automatically directional support.

Negated evidence is retained for auditability but contributes zero directional weight.

Conditional or uncertain evidence remains directional context but is explicitly qualified and receives a 0.5 multiplier in this transparent v1 research score. If all contributing evidence is qualified, the artifact is `ambiguous`, not `supported`.

The current rule layer intentionally uses conservative local marker detection. It does not claim full linguistic understanding of complex negation or modality.

## Contradiction and abstention

Hawkish and dovish evidence are not averaged into a misleading single sign.

If supported directional evidence exists on both sides, the relevant dimension and/or overall artifact is `contradictory`.

If no directional rule matches the source-backed diff, the result is explicit `abstained` with a reason. The system does not manufacture a sentiment score merely because a document changed.

## Evidence quality is not probability

`CentralBankStanceEvidence.evidence_quality` is a transparent heuristic evidence-quality score used only for research ordering and diagnostics.

The artifact also carries `evidence_quality_is_probability=False`, and construction fails if a caller attempts to label the score as probability.

No Brier score, reliability curve, empirical hit rate, or calibration corpus currently supports probabilistic interpretation of this score.

## Research-only authority boundary

Every artifact is hard-coded:

```text
research_only = true
execution_authority = false
```

The constructor rejects any attempt to create this evidence with execution authority.

v0.7.15 does not change runtime fundamentals, signal fusion, risk sizing, Practice authorization, broker execution, or live-money authority.

## Reproducible offline analysis

The CLI reads the durable v0.7.14 SQLite document lineage and reconstructs the exact predecessor/current diff:

```bash
python scripts/analyze_central_bank_stance.py \
  <official-document-database> \
  --family-id fed_fomc_statement \
  --output stance-evidence.json
```

A current version may also be pinned explicitly with `--current-version-id`.

The command performs no network calls and does not mutate runtime policy.

## CI

`src/forex_trader/research/central_bank_stance.py` and `scripts/analyze_central_bank_stance.py` are explicit Ruff and strict-mypy targets.

Tests cover:

- added hawkish evidence;
- removed-language direction inversion;
- negated matches;
- conditional/uncertain evidence;
- cross-dimension and same-dimension contradictions;
- abstention;
- repeated source phrase matches and unique evidence IDs;
- paragraph/offset/evidence provenance tampering;
- research-only and non-probability construction guards;
- latest and pinned persisted-version CLI analysis.

## Deliberate non-goals

v0.7.15 does not:

- integrate stance into deployable fundamental scores;
- claim the lexicon is comprehensive across institutions or document families;
- use an LLM or external classifier;
- treat evidence-quality as calibrated confidence;
- infer a document family from text similarity;
- change strategy or risk thresholds;
- grant Practice or live-money authority.

## Next research milestone

Before runtime integration, the stance layer needs a source-backed human-reviewed evaluation corpus. The next useful tranche should persist immutable expected direction/disposition labels against exact document-diff/version IDs and report coverage, abstention, false-direction rates, contradiction handling, per-dimension confusion, and institution/document-family cohorts.

Only empirical evaluation should determine whether rules are expanded, replaced with a versioned NLP/LLM model, or calibrated into a probability-like confidence. Until then, abstention is preferable to fabricated certainty.
