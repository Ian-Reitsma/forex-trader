# Forex Trader

A Practice-only FX research and execution platform built around market location, declared liquidity, structure confirmation, point-in-time macro evidence, independent portfolio risk, broker-safe execution, and auditable research.

The project is **not** a promise of profitability and is **not** approved for live-money trading. OANDA integration is locked to fxTrade Practice endpoints.

## Current release: v0.7.15

The deployable decision path remains structure-first:

```text
completed lower/higher candles + point-in-time macro/event context
                              ↓
supply/demand location + declared liquidity sweep/reclaim
                              ↓
pivot-derived structure shift + retest/hold
                              ↓
regime/policy selection + independent confirmation categories
                              ↓
structural invalidation/target + fundamental/cost admissibility
                              ↓
independent portfolio risk authorization
                              ↓
account lock + fresh size-aware quote + send-time revalidation
                              ↓
priceBound + protected OANDA Practice order
                              ↓
reconciliation + protection verification + persistent uncertainty halt
```

EMA, RSI and ATR remain secondary diagnostics rather than substitutes for location, liquidity, and structure. Spot broker tick activity is explicitly treated as a low-confidence activity proxy, not centralized institutional footprint/delta data.

## v0.7.15: research-only central-bank stance evidence

v0.7.15 adds a deterministic research artifact on top of the v0.7.14 source-backed current-vs-prior document diff. It does **not** feed the deployable fundamental score or grant execution authority.

The provenance chain is explicit:

```text
first-party feed
    ↓
raw official document bytes + SHA-256
    ↓
explicit family/version lineage
    ↓
added/removed paragraph text + SHA-256
    ↓
versioned rule + exact character offsets
    ↓
research-only stance evidence
```

`central-bank-statement-rules-v1` uses a deliberately conservative phrase set across policy rate, inflation, labor, growth, balance sheet, FX, and financial-stability dimensions. Every matched span retains its paragraph hash/text, rule ID, exact phrase offsets, lexical direction, effective change direction, weight, and qualification flags.

Change-side semantics matter. Adding hawkish language contributes hawkish evidence; removing the same hawkish language contributes dovish change evidence. Removed dovish language similarly becomes hawkish change evidence.

Negated matches remain auditable but contribute zero directional weight. Conditional or uncertain matches are explicitly qualified and downweighted; qualified-only evidence is `ambiguous`, not `supported`. If supported hawkish and dovish evidence coexist, the artifact remains `contradictory` rather than being averaged into a misleading scalar. If no rule matches, the system explicitly abstains.

`evidence_quality` is a transparent heuristic research score, **not** probability or calibrated confidence. The artifact carries `evidence_quality_is_probability=false` and cannot be constructed as an executable artifact.

Reproduce a stance artifact from persisted v0.7.14 lineage without any network/runtime mutation:

```bash
python scripts/analyze_central_bank_stance.py \
  <official-document-database> \
  --family-id fed_fomc_statement \
  --output stance-evidence.json
```

See `docs/41_V0_7_15_CENTRAL_BANK_STANCE_EVIDENCE.md`.

## v0.7.14: source-backed official document body evidence

v0.7.14 turns accepted v0.7.13 central-bank discoveries into durable text evidence before interpretation.

`OfficialDocumentFamily` makes same-document-family identity explicit configuration. Official bodies are fetched through the canonical official-source client/provider-health recorder, and raw bytes must persist/read back before extraction. Document-body availability is conservatively the actual retrieval time rather than the earlier feed timestamp.

UTF-8 HTML/XHTML and plain text are normalized deterministically with navigation/footer/scripts/styles/forms/head chrome excluded. The normalized text and every paragraph are hash-backed. Standard HTML doctypes are accepted; entity declarations and unsupported formats fail closed.

`OfficialDocumentRepository` maintains append-only SQLite lineage. Every later family version must reference the current latest predecessor and become available later. `compare_document_versions` emits exact added/removed paragraph evidence with hashes.

See `docs/40_V0_7_14_OFFICIAL_DOCUMENT_EVIDENCE.md`.

## v0.7.13: official central-bank document discovery

Configured first-party feeds:

- Federal Reserve press releases: `https://www.federalreserve.gov/feeds/press_all.xml`
- ECB press releases, speeches, interviews, and press-conference transcripts: `https://www.ecb.europa.eu/rss/press.html`

RSS/Atom discoveries retain publisher item identity/title/timestamp, exact first-party URL, raw feed evidence-record ID, feed payload SHA-256, and deterministic discovery ID. Every link is revalidated against the official-source HTTPS allowlist; external/mirror links are retained as rejected evidence and never followed. DTD/entity declarations, malformed roots, duplicate item identities, and invalid/missing timestamps fail closed.

See `docs/39_V0_7_13_OFFICIAL_DOCUMENT_DISCOVERY.md`.

## v0.7.12: first concrete official statistical provider

`OfficialJsonPostClient` keeps canonical read-only query bytes/request SHA-256 separate from response provenance. `BlsPublicDataAdapter` targets the official BLS Public Data API v2, requires BLS-level `REQUEST_SUCCEEDED`, and parses series/year/period/value/latest/footnotes while rejecting malformed or incomplete returned series.

A historical BLS observation is **not automatically a scheduled economic-release event**. The adapter does not fabricate a release time, consensus, revision-publication time, or calendar identity.

See `docs/38_V0_7_12_OFFICIAL_BLS_ADAPTER.md`.

## v0.7.11: point-in-time macro source provenance

The source trust boundary is explicit:

- **OFFICIAL** — first-party actual releases/documents from central banks or statistical agencies.
- **LICENSED** — a separately contracted economic-calendar/consensus source used for pre-release market expectations.

The repository does not embed a commercial consensus vendor.

`RawSourcePayload` retains exact HTTPS URL/content type, publication/availability/retrieval timestamps, raw bytes, raw SHA-256, and a canonical evidence-record SHA-256. `EconomicEventMapping` binds one logical event to one licensed consensus source and one official actual source. Consensus must exist no later than schedule time; official actual evidence cannot exist before it.

`SourceEvidenceRepository`, `ProviderPollRunner`, `MacroIngestionOrchestrator`, and `MacroReadinessEvaluator` provide durable raw evidence, provider health, raw-first normalization, and exact-source pre/post-release readiness.

See `docs/37_V0_7_11_MACRO_SOURCE_ORCHESTRATION.md`.

## Research evidence and component attribution

Research remains separated from execution authority:

```text
normal shadow production signal
        ↓
exact frozen decision-time inputs
        ↓
full + five one-component production reruns
        ↓
read-only future-path maturity on one paired denominator
        ↓
simultaneous five-component paired bootstrap bands
        ↓
chronological calibration / promotion evidence
        ↓
shadow candidate only
```

The five component ablations are `no_fundamentals`, `no_flow`, `no_session`, `no_zone_quality`, and `no_retest`. Promotion-grade component inference uses simultaneous family-wise paired bootstrap bands across the full five-component family. Individual intervals remain diagnostic only.

See `docs/31_PROSPECTIVE_PAIRED_ABLATIONS.md` and `docs/36_V0_7_10_FAMILYWISE_ABLATION_UNCERTAINTY.md`.

## Installation and offline verification

Target Python is 3.13; CI also verifies Python 3.11.

```bash
cd ~/projects
git clone git@github.com:Ian-Reitsma/forex-trader.git
cd forex-trader
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
pip install -e ".[dev]"
cp .env.example .env
pytest --cov=forex_trader --cov-branch --cov-report=term-missing
forex-trader doctor
```

Simulation requires no external credential:

```bash
forex-trader demo --instrument EUR_USD
```

## OANDA Practice validation

Keep OANDA credentials outside source control. Local configuration belongs in `.env`; GitHub-hosted validation uses repository Actions secrets.

The authenticated validation workflow is manual-only, restricted to `main`, serialized, and staged as `read-only`, `round-trip`, and `campaign`. Any stage capable of a Practice write requires an explicit Practice account ID and operator confirmation. The broker-minimum probe fails closed and attempts to close the exact known trade if a fill exists.

See `docs/17_OANDA_PAPER_SETUP.md` and `docs/25_PRACTICE_CAMPAIGN.md`.

## Research workflow

Capture shadow decisions plus production-faithful paired component decisions:

```bash
python scripts/run_practice_campaign.py \
  --all-currency-pairs \
  --max-cycles 1 \
  --evidence-path campaign-evidence.jsonl \
  --decision-evidence-path decision-evidence.jsonl \
  --ablation-evidence-path ablation-decisions.jsonl
```

Mature and assemble paired component evidence:

```bash
python scripts/label_ablation_decisions.py \
  ablation-decisions.jsonl \
  --output matured-ablation-outcomes.jsonl \
  --maximum-bars 24 \
  --entry-slippage-pips 0.10 \
  --exit-slippage-pips 0.10

python scripts/assemble_paired_ablations.py \
  matured-ablation-outcomes.jsonl \
  --primary-dataset-id <dataset_sha256_from_research_report> \
  --output paired-ablation-evidence.json \
  --familywise-confidence 0.90 \
  --bootstrap-iterations 5000 \
  --bootstrap-seed 20260807
```

Research promotion is fail-closed and non-executable. Missing/statistically unresolved evidence yields `insufficient_evidence`; observed empirical/integrity failure yields `rejected`; the strongest successful state is `shadow_candidate`.

## Validation boundary

CI validates editable installation/compilation, dependency integrity, secret scanning, explicit Ruff checks, strict mypy on deterministic production/research/provider/document/stance paths, the full branch-aware pytest suite with an enforced 85% floor, and an executed protected simulation paper-order smoke on Python 3.11 and 3.13.

Software CI does **not** prove authenticated broker behavior, public-provider/feed availability, stance-model validity, or profitability. No authenticated OANDA Practice success is claimed until the separately configured staged validation is run and reviewed.

## Deliberate boundaries

The repository does not:

- expose a live-money execution endpoint;
- fabricate centralized order flow from spot tick counts;
- scrape an unlicensed economic calendar/news source;
- infer consensus from an official actual;
- fabricate scheduled release availability from historical BLS series data;
- trust external/mirror links because they appear in an official feed;
- infer same-document-family identity from title/text similarity;
- treat central-bank stance evidence quality as calibrated probability;
- feed v0.7.15 stance research into deployable signal fusion;
- claim midpoint candle backtests equal executable quote history;
- allow offline research promotion to grant Practice authority;
- allow paired research ablations to submit broker orders.

The next central-bank research milestone is an immutable human-reviewed evaluation corpus tied to exact document-diff/version IDs. Coverage, abstention, false-direction rates, contradiction handling, dimension confusion, and institution/document-family cohorts should determine whether the conservative rules are expanded or replaced by a versioned NLP/LLM model. Runtime integration should occur only after empirical evaluation and calibration support it. A real licensed consensus/calendar adapter is still required once a licensed provider is selected outside Git.
