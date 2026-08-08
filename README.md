# Forex Trader

A Practice-only FX research and execution platform built around market location, declared liquidity, structure confirmation, point-in-time macro evidence, independent portfolio risk, broker-safe execution, and auditable research.

The project is **not** a promise of profitability and is **not** approved for live-money trading. OANDA integration is locked to fxTrade Practice endpoints.

## Current release: v0.7.13

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

## v0.7.13: official central-bank document discovery

v0.7.13 adds provenance-safe first-party document discovery for the Federal Reserve and European Central Bank on top of the v0.7.11 source-trust boundary.

The configured first-party feeds are:

- Federal Reserve press releases: `https://www.federalreserve.gov/feeds/press_all.xml`
- ECB press releases, speeches, interviews, and press-conference transcripts: `https://www.ecb.europa.eu/rss/press.html`

`OfficialFeedDiscovery` supports RSS and Atom structures. Every accepted document retains its publisher item identity/title/timestamp, exact first-party URL, the raw feed evidence-record ID, feed payload SHA-256, and a deterministic discovery ID.

Every document link is revalidated against the existing official-source HTTPS allowlist. External/mirror links are retained in `rejected_external_links` and are never followed.

Feed XML containing DTD or entity declarations is rejected before parsing. Malformed roots, missing required fields, duplicate accepted item identities, missing timezone information, and invalid timestamps also fail closed.

`OfficialDocumentDiscoveryOrchestrator` runs feed polls through `ProviderPollRunner`, persists the exact raw feed snapshot to `SourceEvidenceRepository`, verifies read-back, and therefore makes discovery health/provenance durable before downstream use.

Discovery is deliberately **not** document analysis. v0.7.13 does not fetch the linked body, infer document-family lineage, compare current/prior statements, label hawkish/dovish language, or change any trading authority.

See `docs/39_V0_7_13_OFFICIAL_DOCUMENT_DISCOVERY.md`.

## v0.7.12: first concrete official statistical provider

v0.7.12 adds a provenance-safe U.S. Bureau of Labor Statistics Public Data API v2 adapter on top of the v0.7.11 OFFICIAL/LICENSED source boundary.

### Official JSON query provenance

`OfficialJsonPostClient` supports first-party APIs whose read-only data contract requires JSON `POST`. It keeps the canonical request body and request SHA-256 separate from the raw response bytes and response evidence identity.

Every query still fails closed on non-official configuration, non-allowlisted URLs, final-host escape, non-200 responses, oversized payloads, malformed JSON, or inconsistent request provenance.

### BLS Public Data API v2

`BlsPublicDataAdapter` targets the official BLS Public Data API v2 endpoint and requires BLS-level `REQUEST_SUCCEEDED`, not merely HTTP 200. It parses series ID, year/period, period name, `Decimal` value, latest flag, and footnote code/text pairs.

The adapter rejects unrequested, duplicate, omitted, or malformed series/observations. Its public-query contract is deliberately conservative: 1-25 unique series IDs and at most a 10-year inclusive range. No BLS credential is embedded in Git.

A historical BLS series observation is **not automatically a scheduled economic-release event**. The adapter does not invent a release timestamp, consensus, revision-publication time, or calendar event identity from a BLS historical observation. A later scheduled-release adapter must explicitly prove event identity and official availability time before the value can participate in the v0.7.11 consensus-vs-actual transaction.

See `docs/38_V0_7_12_OFFICIAL_BLS_ADAPTER.md`.

## v0.7.11: point-in-time macro source provenance

The source trust boundary is explicit:

- **OFFICIAL** — first-party actual releases/documents from central banks or statistical agencies.
- **LICENSED** — a separately contracted economic-calendar/consensus source used for pre-release market expectations.

The repository does not embed or pretend to provide a commercial consensus vendor.

`RawSourcePayload` retains source/publisher authority, exact HTTPS URL/content type, publication/availability/retrieval timestamps, raw bytes, raw SHA-256, and a canonical evidence-record SHA-256 that also binds retrieval provenance.

`EconomicEventMapping` binds one logical indicator/currency event to one licensed consensus source and one official actual source. Consensus must exist no later than scheduled release time; the official actual cannot exist before it. Source IDs, schedule, indicator, and currency must all match before release-surprise calculation.

`SourceEvidenceRepository` durably retains raw source payloads and provider-health evidence. `ProviderPollRunner` records HEALTHY, DEGRADED/rate-limited, or UNAVAILABLE state around provider calls.

`MacroIngestionOrchestrator` persists and reads back both licensed and official raw evidence before creating the deterministic existing `MacroObservation.release` record.

`MacroReadinessEvaluator` requires the exact consensus provider pre-release and both consensus plus official provider after release. Missing, stale, unavailable, or rate-limited required sources fail readiness.

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

Promotion-grade component inference uses simultaneous family-wise paired bootstrap bands across the five-component family. Individual per-component intervals remain useful diagnostics but are insufficient for a multi-component promotion decision.

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

CI validates editable installation/compilation, dependency integrity, secret scanning, explicit Ruff checks, strict mypy on deterministic production/research/provider/discovery paths, the full branch-aware pytest suite with an enforced 85% floor, and an executed protected simulation paper-order smoke on Python 3.11 and 3.13.

Software CI does **not** prove authenticated broker behavior, public-provider/feed availability, or profitability. No authenticated OANDA Practice success is claimed until the separately configured staged validation is run and reviewed.

## Deliberate boundaries

The repository does not:

- expose a live-money execution endpoint;
- fabricate centralized order flow from spot tick counts;
- scrape an unlicensed economic calendar/news source;
- infer consensus from an official actual;
- fabricate scheduled release availability from historical BLS series data;
- trust external/mirror links simply because they appear in an official feed;
- infer central-bank stance from feed titles or summaries;
- treat generic sentiment as a substitute for release surprise/revision evidence;
- claim midpoint candle backtests equal executable quote history;
- allow offline research promotion to grant Practice authority;
- allow paired research ablations to submit broker orders.

The next P0 data milestone is first-party document-body acquisition plus deterministic visible-text extraction and explicit current-vs-prior same-document-family lineage/diffs. Only after that evidence exists should stance/NLP classification be added. A real licensed consensus/calendar adapter is still required once a licensed provider is selected and configured outside Git, and real prospective evidence should accumulate before strategy thresholds are reconsidered.
