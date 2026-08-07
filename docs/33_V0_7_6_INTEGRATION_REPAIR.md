# 33 — v0.7.6 Integration Repair

v0.7.6 is a software-integrity release. It does not change OANDA Practice authority, risk limits, strategy thresholds, or live-money boundaries.

## Why this release exists

The v0.7.2-v0.7.5 research-ablation work landed through overlapping branches. The later trees contained useful research contracts, but the authoritative branch inherited several integration inconsistencies:

- package/runtime identity still installed as `0.7.1`;
- paired-ablation tests referenced loader/artifact APIs absent from the merged module;
- research replay tests could not import the script helper under the configured pytest path;
- replay reproducibility hashing was not yet bound to setup/policy/dataset identity;
- production-ablation tests expected access to the exact frozen snapshot payload while the merged snapshot retained only its hash.

The release repairs those inconsistencies before additional strategy work.

## Repaired contracts

### Authoritative implementation identity

`forex_trader.__version__` is `0.7.6`. Setuptools derives the installed distribution version from the same value, FastAPI/OpenAPI exposes that value, and campaign policy fingerprints use the same semantic implementation version plus build revision when available.

### Frozen same-snapshot evidence

`FrozenAblationSnapshot.from_payload()` now stores canonical JSON and its SHA-256 digest together. Construction verifies that retained JSON is canonical and matches the digest. Research evaluators can therefore consume the exact same point-in-time payload rather than merely sharing an opaque identifier.

Legacy/direct hash-only snapshots remain representable for identity-only tests, but `require_payload()` fails closed when actual frozen data are unavailable.

### Paired-ablation evidence

The module again exposes the complete evidence API expected by the paired research path:

- matured JSONL loading;
- complete per-snapshot variant requirements;
- one shared full-policy denominator;
- primary research dataset binding;
- a distinct content hash for the paired-ablation artifact;
- promotion-compatible ablation evidence output.

The primary decision/outcome `dataset_id` and the paired artifact's own hash are deliberately different identities. The former establishes comparability with the primary untouched test; the latter identifies the exact paired result artifact.

### Replay identity

Repeated replay reports do not count as reproducibility evidence merely because two JSON files hash identically. Before hashing, every replay result must identify the same:

- setup-family filter;
- policy fingerprint;
- immutable decision/outcome dataset ID.

Only then are canonical result hashes compared.

### Test/import boundary

Pytest includes both `src` and the repository root in its explicit Python path so operator/research script helpers can be imported in regression tests without runtime path mutation.

## Validation

The repaired implementation head passed on Python 3.11 and Python 3.13:

- installation as `forex-trader==0.7.6`;
- bytecode compilation;
- `pip check`;
- secret-assignment scanning;
- critical Ruff checks;
- strict deterministic-research mypy checks;
- full pytest/coverage;
- executed protected simulation smoke.

The Python 3.11 run reported **366 passed** and **86.07% branch-aware coverage**, above the repository's 85% floor. The exact documentation-aligned release head is revalidated before merge.

## What this release does not prove

It does not prove profitability, authenticated OANDA behavior, or component attribution.

The v0.7.5 `ProductionAblationAdapter` is a fail-closed hook contract. Its current contract tests use synthetic masked evaluators. The static seam audit identifies likely production functions, but static token matches are not evidence that a feature mask traverses the real production decision path.

The next research tranche must therefore wire `no_fundamentals`, `no_flow`, `no_session`, `no_zone_quality`, and `no_retest` into concrete production decision seams. Each variant must consume the exact same frozen payload, remain shadow-only with broker writes disabled, and later mature against the same future path before component expectancy is accepted.
