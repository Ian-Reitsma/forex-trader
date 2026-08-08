# v0.7.14 — Official Document Body Evidence and Lineage

## Purpose

v0.7.14 turns the v0.7.13 first-party document discoveries into durable, source-backed text evidence. It fetches accepted official document bodies, retains raw bytes, extracts deterministic visible text, maintains explicit same-family predecessor lineage, and emits exact current-vs-prior paragraph changes.

This release still does not classify central-bank stance or change trading authority.

## Explicit document families

`OfficialDocumentFamily` defines the family identity used for longitudinal comparison:

- family ID;
- official source ID;
- document type;
- institution;
- currency.

Family membership is configuration. It is not inferred from a feed title, phrase match, URL guess, or NLP model. A document discovered under a different official source cannot be silently assigned to the family.

## Body acquisition and availability

`OfficialDocumentEvidenceOrchestrator` fetches the discovered URL through the canonical `OfficialSourceClient` and `ProviderPollRunner`.

The body retrieval inherits the existing controls:

- first-party HTTPS allowlist;
- final response host validation;
- response status/size failure;
- provider-health recording;
- exact raw response bytes and SHA-256.

Raw body evidence is persisted to `SourceEvidenceRepository` and must read back identically before text extraction proceeds.

The feed item's publisher timestamp remains `published_at`. The document body's `available_at` is conservatively the actual retrieval time. The system does not pretend the feed timestamp proves the page body was already obtainable at that instant.

## Deterministic text extraction

`extract_official_document_text` supports UTF-8 HTML/XHTML and plain text.

For HTML it:

- accepts a normal HTML doctype;
- rejects entity declarations;
- decodes UTF-8 strictly;
- excludes head, script, style, nav, footer, form, button, noscript, svg, aside and similar non-body chrome;
- preserves deterministic block boundaries;
- collapses horizontal whitespace;
- emits a canonical newline-separated paragraph sequence;
- stores SHA-256 of the exact normalized text.

Unsupported document types such as PDF fail closed rather than being passed through an unverified extractor.

## Durable version lineage

`OfficialDocumentRepository` stores append-only family versions in SQLite.

Each version binds:

- explicit family identity;
- feed discovery identity;
- exact document URL and item ID;
- publisher and body-availability timestamps;
- raw source evidence-record ID;
- raw source payload SHA-256;
- extracted text SHA-256;
- normalized text;
- predecessor version ID.

The first version cannot have a predecessor. Every later version must reference the repository's current latest version for that family and must have a later `available_at` time.

Repeated retrieval of the same discovery with the same raw payload/text is idempotent at the version layer. The separate raw retrieval record remains available as source evidence.

## Current-vs-prior evidence

`compare_document_versions` only compares documents from the same explicit family and requires the current version's predecessor to be the supplied previous version.

Paragraph tuples are compared deterministically with `SequenceMatcher(autojunk=False)`. Output contains exact added and removed paragraphs, their original/current paragraph indexes, and SHA-256 for every evidence unit.

The diff is evidence, not a policy interpretation. For example, an added phrase containing `inflation` is not automatically labeled hawkish or dovish.

## CI

The body orchestrator, lineage repository, and official-document evidence model are explicit Ruff and strict-mypy targets in addition to deterministic tests, the full branch-aware coverage gate, and the existing protected simulation paper-order smoke on Python 3.11 and 3.13.

Tests cover HTML chrome exclusion, standard doctype compatibility, plain-text normalization, invalid UTF-8/content types, entity rejection, explicit family validation, point-in-time lineage, predecessor integrity, exact paragraph diffs, repeated retrieval idempotency, source persistence and provider health.

## Deliberate non-goals

v0.7.14 does not:

- assign hawkish/dovish/neutral stance;
- run an LLM or external model;
- convert text-diff volume into confidence;
- infer same-document-family identity from text/title similarity;
- parse unsupported PDFs with an opaque extractor;
- change macro weights, signal-fusion gates, risk limits, Practice authority, or live-money authority.

## Next P0 milestone

The next central-bank intelligence tranche can now operate on trustworthy evidence. A research-only stance extractor should consume `OfficialDocumentDiff`, bind every classification to exact added/removed evidence spans and version IDs, detect negation/uncertainty/conditional language, distinguish supported/ambiguous/contradictory evidence, and carry an explicit rules/model version.

Any confidence produced before empirical calibration must be labeled as an evidence-quality score rather than a calibrated probability.
