# Forex Trader

A Practice-only FX research and execution platform built around market location, declared liquidity, structure confirmation, point-in-time macro evidence, independent portfolio risk, broker-safe execution, and auditable research.

The project is **not** a promise of profitability and is **not** approved for live-money trading. OANDA integration is locked to fxTrade Practice endpoints.

## Current release: v0.7.11

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

## v0.7.11: point-in-time macro source provenance

v0.7.11 closes the first P0 gap between the existing fundamental model and trustworthy external macro evidence.

The source trust boundary is explicit:

- **OFFICIAL** — first-party actual releases/documents from central banks or statistical agencies.
- **LICENSED** — a separately contracted economic-calendar/consensus source used for pre-release market expectations.

The repository does not embed or pretend to provide a commercial consensus vendor. Test fixtures use a synthetic licensed source only to validate the interface.

### Raw-source integrity

`RawSourcePayload` retains the exact response bytes plus:

- source ID, publisher, and authority class;
- exact HTTPS URL and content type;
- `published_at`, `available_at`, and `retrieved_at` timestamps;
- SHA-256 of the raw bytes;
- a canonical evidence-record SHA-256 that also binds retrieval provenance.

`OfficialSourceClient` is read-only. Requested and final URLs must remain within the approved official publisher host. Non-200 responses, host escape, invalid chronology, hash mismatch, and oversized payloads fail closed.

### Exact event identity

`EconomicEventMapping` binds one logical indicator/currency event to one licensed consensus source and one official actual source with explicit directionality, unit, and importance.

`LicensedConsensusEvidence` must exist no later than the scheduled release. `OfficialReleaseEvidence` cannot exist before the scheduled release. Source IDs, scheduled timestamps, indicator, and currency must all match before the existing release-surprise model can consume the pair.

This prevents post-release information from masquerading as consensus and prevents an actual release from being joined to the wrong event.

### Durable evidence and provider health

`SourceEvidenceRepository` persists raw payloads and point-in-time provider-health observations in SQLite. Identical response bytes retrieved at different times retain the same payload hash but distinct evidence-record identities.

`ProviderPollRunner` records source state automatically:

```text
successful poll       -> HEALTHY
explicit rate limit   -> DEGRADED + rate_limited=true, then fail the poll
provider/parser error -> UNAVAILABLE, then fail the poll
stale/missing health  -> UNAVAILABLE at readiness time
```

### Macro ingestion transaction

`MacroIngestionOrchestrator` enforces:

1. licensed consensus polling no later than scheduled release time;
2. official actual polling no earlier than scheduled release time;
3. provider identity matching against the event mapping;
4. exact consensus/actual validation;
5. durable retention of both raw evidence records;
6. deterministic `MacroObservation.release` identity derived from mapping + raw evidence identities;
7. append through the existing macro-observation sink only after raw evidence is verifiably retained.

There is no broker-write path in this orchestration layer.

### Event-specific readiness

`MacroReadinessEvaluator` requires the providers that actually feed the event:

```text
pre-release  -> licensed consensus source required
post-release -> licensed consensus + official actual source required
```

Missing, stale, unavailable, or rate-limited required sources fail readiness. Quote/candle/account/reconciliation readiness remains owned by the existing system gates.

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

v0.7.11 also repairs release-state drift inherited from v0.7.10: family-wise production code had been merged while several tests and the runtime version identity still reflected v0.7.9. The release aligns tests/runtime identity with the already-merged family-wise contract; it does not weaken that contract.

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

CI validates:

- editable package installation and compilation;
- dependency integrity;
- secret-assignment scanning;
- explicit Ruff critical-path checks;
- strict mypy on deterministic production/research/macro source paths;
- full branch-aware pytest coverage with an enforced 85% floor;
- executed protected simulation paper-order smoke;
- Python 3.11 and Python 3.13.

Software CI does **not** prove authenticated broker behavior, external macro-provider availability, or profitability. No authenticated OANDA Practice success is claimed until the separately configured staged validation is run and reviewed.

## Deliberate boundaries

The repository does not:

- expose a live-money execution endpoint;
- fabricate centralized order flow from spot tick counts;
- scrape an unlicensed economic calendar/news source;
- infer consensus from an official actual;
- treat a generic sentiment score as a substitute for scheduled-event surprise/revision evidence;
- claim midpoint candle backtests equal executable quote history;
- allow offline research promotion to grant Practice authority;
- allow paired research ablations to submit broker orders.

The next P0 data milestone is concrete provider integration behind the v0.7.11 contracts: a licensed consensus/calendar adapter plus official scheduled-release/document adapters, with credentials external to Git, exact source freshness carried into campaign/decision evidence, and real prospective evidence accumulated before any strategy threshold is reconsidered.
