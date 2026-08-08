# Forex Trader

A Practice-only FX research and execution platform built around market location, declared liquidity, structure confirmation, point-in-time macro evidence, independent portfolio risk, broker-safe execution, and auditable research.

The project is **not** a promise of profitability and is **not** approved for live-money trading. OANDA integration is locked to fxTrade Practice endpoints.

## Current release: v0.7.14

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

## v0.7.14: source-backed official document body evidence

v0.7.14 turns accepted v0.7.13 central-bank discoveries into durable text evidence without yet assigning a stance.

`OfficialDocumentFamily` makes same-document-family identity explicit configuration rather than a title or NLP heuristic. The body is fetched only through the canonical official-source client and provider-health recorder. Raw body bytes must persist and read back before extraction proceeds.

Document-body `available_at` is conservatively the actual retrieval time. The earlier feed publication timestamp is retained separately and is not treated as proof that the page body was already obtainable at that moment.

`extract_official_document_text` supports UTF-8 HTML/XHTML and plain text. It excludes navigation, footer, scripts, styles, forms, head content and similar chrome, normalizes deterministic paragraph text, and hashes the exact extracted representation. Standard HTML doctypes are accepted; entity declarations and unsupported formats fail closed.

`OfficialDocumentRepository` maintains append-only SQLite lineage. The first family version has no predecessor; every later version must reference the repository's current latest family version and become available later. Repeat retrieval of the same discovery/content is idempotent at the document-version layer while raw retrieval evidence remains retained.

`compare_document_versions` emits exact added and removed paragraphs with paragraph indexes and SHA-256 evidence. It only compares the same explicit family and requires the supplied prior version to be the current version's declared predecessor.

These diffs are evidence, not hawkish/dovish interpretation. No stance classifier, LLM, fundamental-weight change, or execution authority is introduced in v0.7.14.

See `docs/40_V0_7_14_OFFICIAL_DOCUMENT_EVIDENCE.md`.

## v0.7.13: official central-bank document discovery

v0.7.13 adds provenance-safe first-party document discovery for the Federal Reserve and European Central Bank.

Configured feeds:

- Federal Reserve press releases: `https://www.federalreserve.gov/feeds/press_all.xml`
- ECB press releases, speeches, interviews, and press-conference transcripts: `https://www.ecb.europa.eu/rss/press.html`

`OfficialFeedDiscovery` supports RSS and Atom structures. Every accepted document retains publisher item identity/title/timestamp, exact first-party URL, raw feed evidence-record ID, feed payload SHA-256, and deterministic discovery ID.

Every document link is revalidated against the official-source HTTPS allowlist. External/mirror links are retained as rejected evidence and never followed. Feed XML containing DTD/entity declarations, malformed roots, duplicate accepted item identities, and invalid/missing timestamps fail closed.

`OfficialDocumentDiscoveryOrchestrator` records provider health and persists/read-backs the exact raw feed snapshot before returning discoveries.

See `docs/39_V0_7_13_OFFICIAL_DOCUMENT_DISCOVERY.md`.

## v0.7.12: first concrete official statistical provider

v0.7.12 adds a provenance-safe U.S. Bureau of Labor Statistics Public Data API v2 adapter.

`OfficialJsonPostClient` keeps canonical read-only query bytes/request SHA-256 separate from the raw response identity. `BlsPublicDataAdapter` requires BLS-level `REQUEST_SUCCEEDED`, parses series/year/period/value/latest/footnotes, and rejects unrequested, duplicate, omitted or malformed series.

A historical BLS observation is **not automatically a scheduled economic-release event**. The adapter does not fabricate release time, consensus, revision-publication time, or calendar identity.

See `docs/38_V0_7_12_OFFICIAL_BLS_ADAPTER.md`.

## v0.7.11: point-in-time macro source provenance

The source trust boundary is explicit:

- **OFFICIAL** — first-party actual releases/documents from central banks or statistical agencies.
- **LICENSED** — a separately contracted economic-calendar/consensus source used for pre-release market expectations.

The repository does not embed or pretend to provide a commercial consensus vendor.

`RawSourcePayload` retains exact HTTPS URL/content type, publication/availability/retrieval timestamps, raw bytes, raw SHA-256, and a canonical evidence-record SHA-256 binding retrieval provenance.

`EconomicEventMapping` binds one logical indicator/currency event to one licensed consensus source and one official actual source. Consensus must exist no later than scheduled release time; official actual evidence cannot exist before it. Source IDs, schedule, indicator, and currency must match before release-surprise calculation.

`SourceEvidenceRepository`, `ProviderPollRunner`, `MacroIngestionOrchestrator`, and `MacroReadinessEvaluator` provide durable raw evidence, health recording, raw-first normalization, and exact-source pre/post-release readiness.

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

The five component ablations are `no_fundamentals`, `no_flow`, `no_session`, `no_zone_quality`, and `no_retest`. They rerun real production seams on one frozen snapshot and cannot submit broker orders.

Promotion-grade component inference uses simultaneous family-wise paired bootstrap bands across the five-component family. Individual per-component intervals remain diagnostic only and are insufficient for a multi-component promotion decision.

See:

- `docs/31_PROSPECTIVE_PAIRED_ABLATIONS.md`
- `docs/34_V0_7_8_PAIRED_OUTCOME_MATURITY.md`
- `docs/35_V0_7_9_PAIRED_ABLATION_UNCERTAINTY.md`
- `docs/36_V0_7_10_FAMILYWISE_ABLATION_UNCERTAINTY.md`

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

The authenticated validation workflow is manual-only, restricted to `main`, serialized, and staged as `read-only`, `round-trip`, and `campaign`. Any stage capable of a Practice write requires the explicit Practice account ID and operator confirmation.

The broker-minimum probe fails closed. Once a known fill exists it attempts to close that exact trade even if protection verification fails, and failed or unverifiable close state remains a critical reconciliation condition.

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

Mature complete paired groups with read-only OANDA Practice candles:

```bash
python scripts/label_ablation_decisions.py \
  ablation-decisions.jsonl \
  --output matured-ablation-outcomes.jsonl \
  --maximum-bars 24 \
  --entry-slippage-pips 0.10 \
  --exit-slippage-pips 0.10
```

Assemble simultaneous family-wise component evidence:

```bash
python scripts/assemble_paired_ablations.py \
  matured-ablation-outcomes.jsonl \
  --primary-dataset-id <dataset_sha256_from_research_report> \
  --output paired-ablation-evidence.json \
  --familywise-confidence 0.90 \
  --bootstrap-iterations 5000 \
  --bootstrap-seed 20260807
```

Ordinary decision/outcome analysis remains available:

```bash
python scripts/label_decision_evidence.py \
  decision-evidence.jsonl \
  --output outcome-evidence.jsonl

python scripts/analyze_research_dataset.py \
  decision-evidence.jsonl \
  outcome-evidence.jsonl \
  --setup-family zone_continuation
```

Research promotion is fail-closed and non-executable. Missing or statistically unresolved evidence yields `insufficient_evidence`; observed empirical/integrity failure yields `rejected`; the strongest successful state is `shadow_candidate`.

## Validation boundary

CI validates editable installation/compilation, dependency integrity, secret scanning, explicit Ruff checks, strict mypy on deterministic production/research/provider/document-evidence paths, the full branch-aware pytest suite with an enforced 85% floor, and an executed protected simulation paper-order smoke on Python 3.11 and 3.13.

Software CI does **not** prove authenticated broker behavior, public-provider/feed availability, or profitability. No authenticated OANDA Practice success is claimed until the separately configured staged validation is run and reviewed.

## Deliberate boundaries

The repository does not:

- expose a live-money execution endpoint;
- fabricate centralized order flow from spot tick counts;
- scrape an unlicensed economic calendar/news source;
- infer consensus from an official actual;
- fabricate scheduled release availability from historical BLS series data;
- trust external/mirror links simply because they appear in an official feed;
- infer central-bank stance from feed titles, summaries, or raw text-diff count;
- infer same-document-family identity from title/text similarity;
- treat generic sentiment as a substitute for release surprise/revision evidence;
- claim midpoint candle backtests equal executable quote history;
- allow offline research promotion to grant Practice authority;
- allow paired research ablations to submit broker orders.

The next central-bank intelligence milestone is a research-only stance evidence layer built strictly on v0.7.14 current-vs-prior source-backed diffs, with explicit evidence spans, negation/uncertainty/conditional-language handling, contradiction states, and a versioned rules/model contract. Any pre-calibration confidence must be labeled as evidence quality rather than probability. A real licensed consensus/calendar adapter is still required once a licensed provider is selected and configured outside Git, and real prospective evidence should accumulate before strategy thresholds are reconsidered.
