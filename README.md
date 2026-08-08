# Forex Trader

A Practice-only FX research and execution platform built around market location, declared liquidity, structure confirmation, point-in-time macro evidence, independent portfolio risk, broker-safe execution, and auditable research.

The project is **not** a promise of profitability and is **not** approved for live-money trading. OANDA integration is locked to fxTrade Practice endpoints.

## Current release: v0.7.22

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

## v0.7.22: sealed central-bank semantic calibration / holdout

v0.7.22 adds the missing independent holdout boundary for the v0.7.19 blinded human-annotation workflow. It does **not** define a semantic pass threshold, claim that the v0.7.15 stance extractor is semantically valid, or grant runtime/execution authority.

One complete frozen annotation batch is split deterministically in chronological order: the first `floor(2N/3)` packets are calibration and the final one-third are holdout. The split has no random seed, stratification option, user-selectable ratio, or best-looking partition selector. An immutable manifest binds the source batch, family, annotation policy, `as_of`, packet denominator, and exact ordered packet IDs in both partitions.

Calibration and holdout are emitted as normal v0.7.19 annotation batches so the existing blinded reviewer/adjudicator tooling can be reused without a second truth schema. Partition finalization still reconstructs the **complete** official-document source batch before accepting either subset, then rejects partition swaps, cross-partition submissions/adjudications, incomplete packets, cherry-picked reviewer submissions, source drift, or manifest tampering.

“Sealed holdout” is a process/data-access boundary around **human-reviewed/adjudicated truth**, not encryption of public central-bank documents. Semantic acceptance criteria must be selected using calibration labels only, then frozen with the extractor/ruleset/evaluator identity before holdout truth is collected/opened and evaluated once.

```bash
python scripts/create_central_bank_semantic_holdout.py \
  blinded-annotation-batch.json \
  --manifest-output semantic-holdout-manifest.json \
  --calibration-output semantic-calibration-batch.json \
  --holdout-output semantic-holdout-batch.json

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

See `docs/47_V0_7_22_SEMANTIC_HOLDOUT.md` and `docs/48_V0_7_22_RELEASE_MARKER.md`.

## v0.7.19: blinded central-bank semantic annotation

v0.7.19 operationalizes independent human-label collection without exposing stance-model predictions, rule hits, evidence quality, market outcomes, or trading results to reviewers. Frozen batch export is source-complete at one explicit `as_of`; every packet binds exact prior/current official text, provenance, version IDs, paragraph diffs, hashes, and annotation-policy identity.

Each packet requires at least two independent pseudonymous reviewers and an independent adjudicator. Finalization reconstructs the frozen official-document batch, requires adjudication to account for every supplied reviewer submission, and emits the existing v0.7.17 semantic-label schema plus a separate disagreement audit. The repository still bundles no real human semantic corpus.

See `docs/45_V0_7_19_BLINDED_ANNOTATION_WORKFLOW.md`.

## v0.7.18: chronological family-wise central-bank stance statistics

v0.7.18 adds the independent statistical-validation policy for the v0.7.16 research-only FX reaction panels. It does **not** claim that real stance outcomes have passed this gate and it does not grant runtime or execution authority.

The inference policy is frozen before real evaluation: horizons `(5, 15, 60, 240)`, primary horizon 60 minutes, first two-thirds chronological calibration/final one-third untouched holdout, minimum 24 directional events with 16 calibration and 8 holdout, minimum 80% observed-event coverage, 90% simultaneous family-wise confidence, 5,000 joint event-level bootstrap iterations, a required timezone-aware frozen `as_of`, and the fixed 300-second source baseline-delay policy.

Each bootstrap iteration resamples document events once and applies the same resample vector to all four horizons, then takes the maximum absolute mean deviation across the family. This preserves cross-horizon dependence and prevents post-hoc selection of whichever horizon happens to look best.

The strongest possible state is `informational_signal_candidate`, and only when the untouched 60-minute simultaneous lower mean bound is above zero. If the 60-minute simultaneous upper bound is below zero the result is `rejected`; otherwise it is `insufficient_evidence`. Strong secondary horizons cannot override the fixed primary result.

The source remains `completed_midpoint_candle_open_proxy_not_execution`. A favorable result would be informational market-reaction evidence only—not semantic truth, causal attribution, executable P/L, or after-cost expectancy.

```bash
python scripts/validate_central_bank_stance_statistics.py \
  <official-document-database> \
  <candle-archive.jsonl> \
  --family-id fed_fomc_statement \
  --instrument EUR_USD \
  --as-of 2026-08-08T12:00:00+00:00 \
  --output stance-statistical-validation.json
```

See `docs/44_V0_7_18_CENTRAL_BANK_STANCE_STATISTICS.md`.

## v0.7.17: source-bound central-bank semantic validation

v0.7.17 adds the human-ground-truth contract and offline evaluator required to test the v0.7.15 stance extractor semantically. It does **not** claim that semantic validation has passed, and it does not feed stance into deployable fundamentals.

`CentralBankSemanticLabel` binds an adjudicated human judgment to the exact reconstructed v0.7.14 document diff SHA, explicit previous/current version IDs, annotation-policy version, reviewer IDs, adjudication state, overall direction/disposition, and optional policy-dimension labels. Adjudicated truth requires at least two source annotators plus an adjudicator. Unadjudicated records remain visible but are excluded explicitly from scoring.

The evaluator reconstructs every labeled diff from the durable official-document database before scoring it. Missing versions, lineage mismatches, source-diff hash mismatches, duplicate adjudicated truth, and mixed annotation-policy versions fail closed.

`SemanticEvaluationReport` records exact direction/disposition accuracy, abstention, directional coverage/recall, false directional-call rate, contradiction/ambiguity recall, a direction confusion matrix, per-dimension metrics, and institution/document-family cohorts. Market outcomes are never used as linguistic ground truth. The repository contains synthetic test labels only; no real expert-labeled semantic result is claimed.

```bash
python scripts/evaluate_central_bank_stance_semantics.py \
  <official-document-database> \
  <human-label-corpus.jsonl> \
  --output semantic-evaluation.json
```

See `docs/43_V0_7_17_CENTRAL_BANK_SEMANTIC_VALIDATION.md`.

## Central-bank evidence chain

The research chain now separates source integrity, blinded truth collection, semantic evaluation, and market-response statistics:

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
        ↓ model-blinded source packets
v0.7.19 independent human annotation
        ↓
v0.7.22 sealed calibration / holdout truth boundary
        ↓
v0.7.17 semantic evaluation of adjudicated labels

independently:
v0.7.16 FX reaction panels
        ↓
v0.7.18 family-wise market-reaction statistics

semantic gate + market-response gate
        ↓
no runtime authority yet
```

Recent milestone documents:

- `docs/37_V0_7_11_MACRO_SOURCE_ORCHESTRATION.md` — OFFICIAL/LICENSED source provenance, raw-first storage, exact event mapping and readiness.
- `docs/38_V0_7_12_OFFICIAL_BLS_ADAPTER.md` — provenance-safe BLS Public Data API v2 observations without fabricated release timing.
- `docs/39_V0_7_13_OFFICIAL_DOCUMENT_DISCOVERY.md` — first-party Federal Reserve and ECB feed discovery with external-link rejection.
- `docs/40_V0_7_14_OFFICIAL_DOCUMENT_EVIDENCE.md` — raw official body retention, deterministic visible text, lineage, and exact paragraph diffs.
- `docs/41_V0_7_15_CENTRAL_BANK_STANCE_EVIDENCE.md` — source-span-bound research stance with negation/uncertainty/conditional/contradiction handling.
- `docs/42_V0_7_16_CENTRAL_BANK_STANCE_OUTCOMES.md` — complete-horizon point-in-time FX reaction panels; midpoint proxy, not execution.
- `docs/43_V0_7_17_CENTRAL_BANK_SEMANTIC_VALIDATION.md` — human label provenance and semantic evaluation contract.
- `docs/44_V0_7_18_CENTRAL_BANK_STANCE_STATISTICS.md` — frozen chronological family-wise market-reaction inference.
- `docs/45_V0_7_19_BLINDED_ANNOTATION_WORKFLOW.md` — model/outcome-blinded source-complete human annotation and adjudication.
- `docs/47_V0_7_22_SEMANTIC_HOLDOUT.md` — immutable chronological semantic calibration/holdout partition and anti-leakage workflow.
- `docs/48_V0_7_22_RELEASE_MARKER.md` — release identity and authority boundary.

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

CI validates editable installation/compilation, dependency integrity, secret scanning, explicit Ruff checks, strict mypy on deterministic production/research/provider/document/stance/outcome/semantic/statistical paths, the full branch-aware pytest suite with an enforced 85% floor, and an executed protected simulation paper-order smoke on Python 3.11 and 3.13.

The separate `Annotation integrity` workflow directly lints, strict-types, and regression-tests the blinded annotation and semantic-holdout modules/operator paths on Python 3.11 and 3.13.

Software CI does **not** prove authenticated broker behavior, public-provider availability, human reviewer quality, stance-model semantic validity, causal event impact, real-world statistical edge, executable stance expectancy, or profitability.

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
- use market direction as semantic ground truth;
- expose stance-model predictions or market outcomes to the supported blinded-review packet;
- let holdout truth determine semantic acceptance thresholds;
- claim a semantic acceptance threshold before real calibration evidence exists;
- let a favorable secondary horizon replace the predeclared 60-minute statistical primary;
- feed v0.7.15-v0.7.22 stance/semantic research into deployable signal fusion;
- treat favorable midpoint direction as executable profit;
- allow offline research promotion to grant Practice authority;
- allow paired research ablations to submit broker orders.

The next semantic evidence requirement is real independently reviewed calibration data, not another synthetic success claim. Calibration labels should be evaluated under v0.7.17, semantic acceptance criteria should then be predeclared and frozen, and only afterward should holdout truth be finalized for one independent evaluation. Separately, a real point-in-time stance-outcome sample must survive the frozen v0.7.18 market-reaction policy. Only if both independent gates survive should an after-cost execution study be considered. A real licensed consensus/calendar adapter is still required once a licensed provider is selected outside Git.
