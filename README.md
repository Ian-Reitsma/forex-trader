# Forex Trader

A Practice-only FX research and execution platform built around explicit market location, declared liquidity, structure confirmation, point-in-time macro context, independent portfolio risk, broker-safe execution, and auditable research evidence.

The codebase is **not** a promise of profitability and is **not** approved for live-money trading. OANDA integration is locked to fxTrade Practice endpoints.

## Current release: v0.7.9

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

Research is intentionally separated from execution authority:

```text
normal shadow production signal
        ↓
exact frozen decision-time inputs
        ↓
full + five one-component production reruns
        ↓
read-only future-path maturity on one paired denominator
        ↓
paired full-minus-ablated delta + confidence bounds
        ↓
chronological calibration / promotion evidence
        ↓
shadow candidate only
```

EMA, RSI and ATR are secondary diagnostics rather than substitutes for location, liquidity, and market structure. Spot broker tick activity is explicitly treated as a low-confidence activity proxy, not centralized footprint/delta order flow.

## v0.7.9 paired component uncertainty

v0.7.9 replaces raw-mean-only component promotion decisions with deterministic paired uncertainty on the exact per-snapshot counterfactual:

```text
component_increment_r = full_realized_r - ablated_realized_r
```

Positive delta means the component helped the full policy on that exact frozen snapshot; negative delta means the one-component ablation did better.

- The assembler reuses the existing Phase-D paired-bootstrap mean interval rather than introducing a separate statistical implementation.
- Defaults are **90% confidence**, **2,000 bootstrap iterations**, and deterministic seed **20260807**.
- Every component row records the mean increment, lower/upper paired confidence bounds, paired win/loss/tie counts, sample size, primary dataset ID, confidence level, iterations, and seed.
- The uncertainty artifact records the bootstrap method and delta semantics, and validates its paired artifact SHA-256 identity.
- Promotion no longer trusts the dataset ID string alone: every required component must also match the primary untouched-test sample count and full-policy expectancy.
- Legacy mean-only ablation artifacts remain loadable, but they are `insufficient_evidence` because they lack uncertainty provenance.
- Promotion distinguishes uncertainty from observed harm using the existing 0.05R material-harm tolerance:

```text
upper confidence bound < -0.05R
    -> rejected: component is confidently materially harmful

lower bound < -0.05R <= upper bound
    -> insufficient evidence: material harm cannot yet be ruled out

lower bound >= -0.05R
    -> component non-harm check passes; every other promotion gate still applies
```

This is an evidence-quality improvement only. No strategy threshold, risk limit, setup authority, Practice authority, or broker execution behavior is changed.

## v0.7.8 paired outcome maturity

v0.7.8 completes the prospective component-ablation evidence lifecycle from frozen decision capture through conservative future-path labeling:

- Every prospective ablation row carries the exact decision-time bid/ask used by the frozen production snapshot. Full-policy capture verifies those quote values against the actual production trace before rows are accepted.
- Prospective JSONL loading rejects duplicate variants, inconsistent snapshot identities/quotes, and incomplete six-variant groups.
- Nontradeable variants remain in the paired denominator at `0R`; evaluator failures are also explicit `0R` rows rather than disappearing from the sample.
- Maturity is atomic by snapshot. If any tradeable sibling is still waiting for a terminal stop/target or the complete timeout horizon, none of that snapshot's six outcomes are appended yet.
- Tradeable variants reuse the same `evaluate_candidate_outcome` engine as ordinary research evidence: captured spread, entry/exit slippage, gap-through stops, conservative stop-first same-bar ambiguity, and timeout R are handled by one outcome implementation.
- A tradeable row without captured quote context fails closed instead of silently assuming zero spread.
- Matured rows retain label policy/time, bars held, exit reason, ambiguity, and estimated cost R. The paired artifact hash binds that provenance as well as realized R/status.
- `scripts/label_ablation_decisions.py` uses read-only OANDA Practice historical candles only. It has no order submission or close path and validates existing output as complete six-variant groups before resuming.

These outcomes are empirical research evidence, not execution authority. A small or unfavorable sample is not a reason to lower production gates.

## v0.7.7 production-faithful paired capture

v0.7.7 moved component attribution into the actual production signal path while preserving the existing Practice authority boundary:

- `fundamentals`, `flow`, `session`, `zone_quality`, and `retest` have explicit default-on production decision seams. Ordinary runtime calls remain all-on; only research requests can disable one component at a time.
- The full and masked variants rerun the real `assess_technicals` and `RegimeAwareSignalFusionPolicy` logic. Disabling a component removes its real score, gate, regime, and independent-confirmation effects rather than changing a synthetic research wrapper.
- Shadow campaign capture freezes the exact lower/higher completed candles, actual returned quote, point-in-time fundamental assessment, adaptive spread ceiling, scheduled-event blackout state, rollover state, policy fingerprint, instrument, and signal time.
- An outer evaluation snapshot reuses the same completed-candle provider responses after the normal production decision. The paired capture path does not request another executable quote or additional underlying candle history.
- The frozen `full` replay must exactly match the actual production candidate on tradeability, setup/direction, score, entry/stop/target geometry, rejection code, and bid/ask quote context before any paired rows are written.
- Scheduled-event blackout is replayed for every variant. Rollover blackout is replayed whenever the session component remains enabled; `no_session` intentionally removes session-derived suppression as part of that single-component counterfactual.
- Paired capture is hard-disabled when campaign execution is enabled. It has no broker submission authority and records research instrumentation errors separately from provider, strategy, risk, and execution errors.

## Runtime and evidence integrity

Supported deployable timeframe policy is lower `M5/M10/M15/M30` with higher `H1/H4`. OANDA bar-start timestamps are converted to completed-bar signal times for no-lookahead freshness logic.

Completed candles may be reused only inside one evaluation for a later smaller same-instrument/same-granularity request. Executable quotes are never cached and candle snapshots do not cross the evaluation boundary. The paired research capture path extends the lifetime of that same completed-candle snapshot only until exact decision inputs are frozen; it does not make a second provider market-data pass.

Fundamentals are immutable point-in-time evidence with component-specific decay, horizon-specific currency context, central-bank comparison, scheduled-event blackouts, and holiday context. They operate as independent admissibility/conflict gates rather than an arbitrary percentage blended into the technical score.

Independent confirmation categories are explicit: price, fundamentals, flow, cross-asset, and execution. Duplicate/syndicated information is not counted as multiple independent sources. Broker tick activity cannot satisfy a policy that requires real institutional flow.

Risk includes lower(balance, NAV) capital sizing, broker-priced currency conversion, a persistent 5-p.m.-New-York marked-loss circuit, position/unit limits, gross currency exposure, concentration, margin reserve, signed recent-return correlation veto, trailing drawdown, loss-streak observation, reserved risk, and gap-stress loss.

Campaign evidence includes a secret-free policy fingerprint plus semantic implementation version and exact build revision when available. Mixed policy/build cohorts cannot be silently pooled by the analyzer.

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

Simulation is the default provider and requires no external credential:

```bash
forex-trader demo --instrument EUR_USD
```

## OANDA Practice validation

Keep OANDA credentials outside source control. Local configuration belongs in `.env`; GitHub-hosted validation uses repository Actions secrets.

The authenticated validation workflow is manual-only, restricted to `main`, serialized so broker-validation runs cannot overlap, and has explicit `read-only`, `round-trip`, and `campaign` stages. Read-only may discover the authorized Practice account from the token; any stage capable of submitting a Practice order additionally requires an explicit Practice account ID and operator confirmation.

The broker-minimum round-trip helper fails closed. Once a known fill exists, it attempts to close that exact probe trade even if protection verification fails or raises, and failed/unverifiable close state is a critical reconciliation condition.

See `docs/17_OANDA_PAPER_SETUP.md` and `docs/25_PRACTICE_CAMPAIGN.md`.

## Research evidence workflow

Capture detailed shadow decisions and the prospective paired component stream in one campaign:

```bash
python scripts/run_practice_campaign.py \
  --all-currency-pairs \
  --max-cycles 1 \
  --evidence-path campaign-evidence.jsonl \
  --decision-evidence-path decision-evidence.jsonl \
  --ablation-evidence-path ablation-decisions.jsonl
```

`--ablation-evidence-path` is shadow-only. Combining it with `--execute` is rejected before the campaign starts. Each successful instrument capture writes exactly six rows: `full`, `no_fundamentals`, `no_flow`, `no_session`, `no_zone_quality`, and `no_retest`, all sharing one immutable snapshot payload hash, policy fingerprint, and decision-time quote context.

After the paired future-price horizon matures, label complete snapshot groups using read-only OANDA Practice candles:

```bash
python scripts/label_ablation_decisions.py \
  ablation-decisions.jsonl \
  --output matured-ablation-outcomes.jsonl \
  --maximum-bars 24 \
  --entry-slippage-pips 0.10 \
  --exit-slippage-pips 0.10
```

The labeler writes a snapshot only when all six variants are mature. No-trade variants are retained at 0R; incomplete tradeable horizons remain pending.

Then assemble paired component expectancy and uncertainty against the same primary research dataset:

```bash
python scripts/assemble_paired_ablations.py \
  matured-ablation-outcomes.jsonl \
  --primary-dataset-id <dataset_sha256_from_research_report> \
  --output zone-continuation-ablations.json \
  --confidence 0.90 \
  --bootstrap-iterations 2000 \
  --bootstrap-seed 20260807
```

The ordinary decision/outcome workflow remains available:

```bash
python scripts/label_decision_evidence.py \
  decision-evidence.jsonl \
  --output outcome-evidence.jsonl

python scripts/analyze_research_dataset.py \
  decision-evidence.jsonl \
  outcome-evidence.jsonl \
  --setup-family zone_continuation
```

For paired Phase-D entry/management research:

```bash
python scripts/analyze_phase_d_paths.py \
  decision-evidence.jsonl \
  candle-archive.jsonl
```

Research promotion remains fail-closed and non-executable. Missing or statistically unresolved evidence yields `insufficient_evidence`; observed empirical/integrity failure yields `rejected`; the strongest successful state is `shadow_candidate`.

See `docs/27_RESEARCH_EVIDENCE_AND_EV.md`, `docs/28_PHASE_D_PAIRED_COUNTERFACTUALS.md`, `docs/29_RESEARCH_PROMOTION_BUNDLE.md`, `docs/31_PROSPECTIVE_PAIRED_ABLATIONS.md`, `docs/33_V0_7_7_AUTOMATIC_PAIRED_CAPTURE.md`, `docs/34_V0_7_8_PAIRED_OUTCOME_MATURITY.md`, and `docs/35_V0_7_9_PAIRED_ABLATION_UNCERTAINTY.md`.

## Current validation

The v0.7.9 documentation/version head passed the full Python 3.11 and Python 3.13 matrices with the expanded production/research quality gates. On Python 3.11:

- **394 tests passed**;
- **85.72% branch-aware coverage**;
- repository coverage floor: **85%**;
- expanded critical Ruff checks passed across the capture, maturity, uncertainty, promotion, and CLI surfaces;
- expanded strict mypy passed across the deterministic production/research paths and uncertainty/promotion commands;
- dynamic package installation, bytecode compilation, `pip check`, and secret-assignment scan passed;
- the executed protected simulation paper-order smoke passed.

The final README-aligned v0.7.9 head is revalidated before merge.

Software CI does **not** prove authenticated broker behavior or trading profitability. No OANDA Practice success is claimed until the externally configured staged validation is run and its evidence is reviewed.

## Deliberate boundaries

The repository does not expose a live-money execution endpoint, fabricate centralized order flow from spot tick counts, substitute unlicensed scraping for production news/economic-calendar feeds, claim midpoint candle backtests equal executable quote history, grant runtime authority to unvalidated scale-out/runner logic, treat an offline research nomination as Practice authority, or let paired research ablations submit broker orders.

The next evidence milestone is real data, not looser gates: accumulate a meaningful prospective capture/maturity corpus and measure whether fundamentals, flow, session, zone quality, or retest provide positive after-cost incremental expectancy with sufficiently narrow paired confidence bounds on untouched chronological evidence. Authenticated OANDA Practice evidence and that immutable corpus should determine whether the actual bottleneck is data coverage, setup formation, market/execution conditions, portfolio constraints, component value, entry/management policy, or strategy expectancy before production thresholds are changed.
