# Forex Trader

A Practice-only FX research and execution platform built around explicit market location, declared liquidity, structure confirmation, point-in-time macro context, independent portfolio risk, broker-safe execution, and auditable research evidence.

The codebase is **not** a promise of profitability and is **not** approved for live-money trading. OANDA integration is locked to fxTrade Practice endpoints.

## Current release: v0.7.6

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
point-in-time decision evidence
        ↓
mature outcome labels
        ↓
chronological calibration + conservative after-cost EV
        ↓
paired Phase-D entry/management counterfactuals
        ↓
prospective paired component ablations on frozen snapshots
        ↓
setup-isolated research-promotion bundle
        ↓
shadow candidate only
```

EMA, RSI and ATR are secondary diagnostics rather than substitutes for location, liquidity, and market structure. Spot broker tick activity is explicitly treated as a low-confidence activity proxy, not centralized footprint/delta order flow.

## v0.7.6 integration repair

v0.7.6 repairs merge drift introduced while the v0.7.2-v0.7.5 research-ablation work was landing concurrently:

- authoritative package/distribution/OpenAPI/campaign identity is again synchronized at `0.7.6`;
- paired-ablation matured-outcome loading, primary-dataset binding, paired-artifact hashing, and evidence writing are restored as one coherent API;
- frozen ablation snapshots retain canonical immutable payload JSON as well as its SHA-256 identity so full and masked evaluators can consume the exact same point-in-time market snapshot;
- pytest can import operator/research script helpers without runtime `sys.path` mutation;
- repeated replay evidence is accepted only when setup family, policy fingerprint, and immutable dataset identity match the primary research report before canonical hashes are compared;
- all ablation/runtime surfaces remain shadow/research-only and cannot enable broker writes.

The production-ablation adapter added in v0.7.5 is deliberately a **contract**, not yet proof of real component attribution. It requires explicit hooks for `no_fundamentals`, `no_flow`, `no_session`, `no_zone_quality`, and `no_retest`, but synthetic hooks do not establish that those masks traverse the real production decision path. The next research tranche wires those masks into concrete production seams and verifies same-snapshot differences prospectively.

## Runtime and evidence integrity

Supported deployable timeframe policy is lower `M5/M10/M15/M30` with higher `H1/H4`. OANDA bar-start timestamps are converted to completed-bar signal times for no-lookahead freshness logic.

Completed candles may be reused only inside one evaluation for a later smaller same-instrument/same-granularity request. Executable quotes are never cached and candle snapshots do not cross the evaluation boundary.

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

Capture detailed shadow decisions:

```bash
python scripts/run_practice_campaign.py \
  --all-currency-pairs \
  --max-cycles 1 \
  --evidence-path campaign-evidence.jsonl \
  --decision-evidence-path decision-evidence.jsonl
```

After the outcome horizon matures, label them using read-only OANDA market data:

```bash
python scripts/label_decision_evidence.py \
  decision-evidence.jsonl \
  --output outcome-evidence.jsonl
```

Analyze one setup family chronologically:

```bash
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

For matured paired component-ablation evidence:

```bash
python scripts/assemble_paired_ablations.py \
  matured-ablation-outcomes.jsonl \
  --primary-research-report zone-continuation-research.json \
  --output zone-continuation-ablations.json
```

Research promotion remains fail-closed and non-executable. Missing evidence yields `insufficient_evidence`; observed empirical/integrity failure yields `rejected`; the strongest successful state is `shadow_candidate`.

See `docs/27_RESEARCH_EVIDENCE_AND_EV.md`, `docs/28_PHASE_D_PAIRED_COUNTERFACTUALS.md`, `docs/29_RESEARCH_PROMOTION_BUNDLE.md`, `docs/31_PROSPECTIVE_PAIRED_ABLATIONS.md`, and `docs/32_V0_7_4_SHADOW_ABLATION_RUNTIME.md`.

## Current validation

The v0.7.6 repair implementation head passed both Python 3.11 and Python 3.13 through install, bytecode compilation, dependency integrity, secret scanning, critical Ruff checks, strict deterministic-research typing, full pytest/coverage, and the executed protected simulation smoke.

On Python 3.11 the full suite reported:

- **366 tests passed**;
- **86.07% branch-aware coverage**;
- repository coverage floor: **85%**.

The exact documentation-aligned v0.7.6 head is revalidated before merge.

Software CI does **not** prove authenticated broker behavior or trading profitability. No OANDA Practice success is claimed until the externally configured staged validation is run and its evidence is reviewed.

## Deliberate boundaries

The repository does not expose a live-money execution endpoint, fabricate centralized order flow from spot tick counts, substitute unlicensed scraping for production news/economic-calendar feeds, claim midpoint candle backtests equal executable quote history, grant runtime authority to unvalidated scale-out/runner logic, or treat an offline research nomination as Practice authority.

The next evidence milestone is twofold: restore a fully green authoritative `main`, then wire the prospective ablation masks into real production decision seams on one frozen snapshot. Authenticated OANDA Practice evidence and a meaningful immutable decision/outcome/path corpus should determine whether the actual bottleneck is data coverage, setup formation, market/execution conditions, portfolio constraints, component value, entry/management policy, or strategy expectancy before production thresholds are changed.
