# Forex Trader

A Practice-only FX research and execution platform built around market location, declared liquidity, structure confirmation, point-in-time macro evidence, independent portfolio risk, broker-safe execution, and auditable research.

The project is **not** a promise of profitability and is **not** approved for live-money trading. OANDA integration is locked to fxTrade Practice endpoints.

## Current release: v0.7.17

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

EMA, RSI and ATR remain secondary diagnostics rather than substitutes for location, liquidity, and structure. Spot broker tick activity is explicitly a low-confidence activity proxy, not centralized institutional footprint/delta data.

## v0.7.17: source-bound central-bank semantic validation

v0.7.17 adds the human-ground-truth contract and offline evaluator required to test the v0.7.15 stance extractor semantically. It does **not** claim that semantic validation has passed, and it does not feed stance into deployable fundamentals.

`CentralBankSemanticLabel` binds an adjudicated human judgment to the exact reconstructed v0.7.14 document diff SHA, explicit previous/current version IDs, annotation-policy version, reviewer IDs, adjudication state, overall direction/disposition, and optional policy-dimension labels. Adjudicated truth requires at least two source annotators plus an adjudicator. Unadjudicated records remain visible but are excluded explicitly from scoring.

The evaluator reconstructs every labeled diff from the durable official-document database before scoring it. Missing versions, lineage mismatches, source-diff hash mismatches, duplicate adjudicated truth, and mixed annotation-policy versions fail closed.

`SemanticEvaluationReport` records exact direction/disposition accuracy, abstention, directional coverage/recall, false directional-call rate, contradiction/ambiguity recall, a direction confusion matrix, per-dimension metrics, and institution/document-family cohorts. The report SHA binds the implementation version, stance ruleset, annotation policy, metrics, evaluated label IDs, and unadjudicated exclusions.

Market outcomes are never used as linguistic ground truth. The repository contains synthetic test labels only; no real expert-labeled semantic result is claimed.

```bash
python scripts/evaluate_central_bank_stance_semantics.py \
  <official-document-database> \
  <human-label-corpus.jsonl> \
  --output semantic-evaluation.json
```

See `docs/43_V0_7_17_CENTRAL_BANK_SEMANTIC_VALIDATION.md`.

## Central-bank evidence chain

The research chain now separates source integrity, interpretation, semantic truth, and market response:

```text
first-party Fed/ECB discovery
        ↓
raw official body bytes + SHA-256
        ↓
explicit same-family version lineage
        ↓
source-backed current-vs-prior paragraph diff
        ↓
v0.7.15 deterministic research-only stance artifact
       ↙                                      ↘
v0.7.17 human semantic evaluation      v0.7.16 FX reaction outcomes
       ↓                                      ↓
semantic evidence                      statistical market evidence
                 \                    /
                  independent gates
                        ↓
              no runtime authority yet
```

Recent milestone documents:

- `docs/37_V0_7_11_MACRO_SOURCE_ORCHESTRATION.md` — OFFICIAL/LICENSED source provenance, raw-first storage, exact event mapping and readiness.
- `docs/38_V0_7_12_OFFICIAL_BLS_ADAPTER.md` — provenance-safe BLS Public Data API v2 observations without fabricated release timing.
- `docs/39_V0_7_13_OFFICIAL_DOCUMENT_DISCOVERY.md` — first-party Federal Reserve and ECB feed discovery with external-link rejection.
- `docs/40_V0_7_14_OFFICIAL_DOCUMENT_EVIDENCE.md` — raw official body retention, deterministic visible text, lineage, and exact paragraph diffs.
- `docs/41_V0_7_15_CENTRAL_BANK_STANCE_EVIDENCE.md` — source-span-bound research stance with negation/uncertainty/conditional/contradiction handling.
- `docs/42_V0_7_16_CENTRAL_BANK_STANCE_OUTCOMES.md` — complete-horizon, point-in-time FX market-reaction panels; midpoint proxy, not execution.
- `docs/43_V0_7_17_CENTRAL_BANK_SEMANTIC_VALIDATION.md` — human label provenance and semantic evaluation contract.

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

The component family is `no_fundamentals`, `no_flow`, `no_session`, `no_zone_quality`, and `no_retest`. Promotion-grade component inference uses simultaneous family-wise paired bootstrap bands across the full five-component family; individual intervals remain diagnostic only.

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

## Validation boundary

CI validates editable installation/compilation, dependency integrity, secret scanning, explicit Ruff checks, strict mypy on deterministic production/research/provider/document/stance/outcome/semantic paths, the full branch-aware pytest suite with an enforced 85% floor, and an executed protected simulation paper-order smoke on Python 3.11 and 3.13.

Software CI does **not** prove authenticated broker behavior, public-provider availability, stance-model semantic validity, causal event impact, executable stance expectancy, or profitability.

## Deliberate boundaries

The repository does not:

- expose a live-money execution endpoint;
- fabricate centralized order flow from spot tick counts;
- scrape an unlicensed economic calendar/news source;
- infer consensus from an official actual;
- fabricate release availability from historical BLS series data;
- trust external/mirror links because they appear in an official feed;
- infer same-document-family identity from title/text similarity;
- treat central-bank stance evidence quality as calibrated probability;
- use v0.7.16 market direction as semantic ground truth;
- feed v0.7.15-v0.7.17 stance research into deployable signal fusion;
- treat favorable midpoint direction as executable profit;
- allow offline research promotion to grant Practice authority;
- allow paired research ablations to submit broker orders.

The next central-bank evidence requirement is a **real**, independently human-reviewed and adjudicated corpus evaluated on a predeclared holdout. In parallel, v0.7.16 market outcomes need chronological uncertainty analysis with simultaneous treatment of the full 5/15/60/240-minute horizon family. Only if semantic and statistical validation both survive should after-cost execution research be considered. A real licensed consensus/calendar adapter is still required once a licensed provider is selected outside Git.
