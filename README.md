# Forex Trader

A Practice-only FX research and execution platform built around explicit market location, declared liquidity, structure confirmation, point-in-time macro context, independent portfolio risk, broker-safe execution and auditable evidence.

The codebase is **not** a promise of profitability and is **not** approved for live-money trading. OANDA integration is locked to fxTrade Practice endpoints.

## Current release: v0.7.0

The deployable path is structure-first:

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
independent currency/margin/correlation/drawdown risk authorization
                              ↓
account lock + fresh size-aware quote + send-time revalidation
                              ↓
priceBound + protected OANDA Practice order
                              ↓
reconciliation + protection verification + persistent uncertainty halt
                              ↓
per-cycle operations evidence + point-in-time per-decision research evidence
                              ↓
mature outcome labeling + chronological cohort calibration + research EV analysis
```

EMA, RSI and ATR are secondary diagnostics rather than substitutes for location, liquidity and market structure. Spot broker tick activity is explicitly treated as a low-confidence activity proxy, not centralized footprint/delta order flow.

## Runtime and evidence integrity

Supported deployable timeframe policy is lower `M5/M10/M15/M30` with higher `H1/H4`. OANDA bar-start timestamps are converted to completed-bar signal times for no-lookahead freshness logic.

Within one FX evaluation, completed candles may be reused for a later smaller same-instrument/same-granularity request. Executable quotes are never cached and candle snapshots never cross the evaluation boundary.

Fundamentals are immutable point-in-time evidence with component-specific decay, horizon-specific currency context, central-bank comparison, scheduled-event blackouts and holiday context. They operate as independent admissibility/conflict gates rather than an arbitrary percentage blended into the technical score.

Independent confirmation categories are explicit: price, fundamentals, flow, cross-asset and execution. Duplicate/syndicated information is not counted as multiple independent sources. Broker tick activity cannot satisfy a policy that requires real institutional flow.

Risk includes lower(balance, NAV) capital sizing, broker-priced currency conversion, a persistent 5-p.m.-New-York marked-loss circuit, position/unit limits, gross currency exposure, concentration, margin reserve, signed recent-return correlation veto, trailing drawdown, loss-streak observation, reserved risk and gap-stress loss. Risk can deny an otherwise valid candidate and never increases size because of low correlation.

Campaign evidence includes a secret-free policy fingerprint plus semantic implementation version and exact build revision when available. Mixed policy/build cohorts cannot be silently pooled by the analyzer.

v0.7.0 also records one point-in-time decision row per instrument attempt when requested. Detailed rows retain setup/regime/session, confirmation categories and sources, candidate geometry, quote, risk result, order state and raw feature evidence. Mature decisions can later be labeled with read-only OANDA candles and evaluated through chronological cohort calibration and a research-only conservative expected-value gate.

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

Keep OANDA credentials outside chat and source control. Local configuration belongs in `.env`; GitHub-hosted validation uses repository Actions secrets.

The authenticated validation workflow is **manual-only**, restricted to `main`, serialized so two broker-validation runs cannot overlap, and has three explicit stages: `read-only`, `round-trip`, and `campaign`. The read-only stage can discover an authorized Practice account from `OANDA_API_TOKEN`; any stage that can submit a Practice order additionally requires an explicit `OANDA_ACCOUNT_ID` and operator confirmation.

The token-only read-only contract is covered end to end with mocked OANDA responses: shadow configuration accepts no account ID, the adapter discovers the authorized Practice account, transaction synchronization continues through that discovered ID, and enabling Practice writes without an explicit account ID remains invalid.

The broker-minimum round-trip helper fails closed: after a known fill it attempts to close that exact probe trade even if protection verification fails or raises, and treats failed/unverifiable close state as a critical reconciliation condition.

See `docs/17_OANDA_PAPER_SETUP.md` for credential/setup and staged workflow details. See `docs/25_PRACTICE_CAMPAIGN.md` for campaign evidence/analysis rules.

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

Then analyze one immutable policy cohort chronologically:

```bash
python scripts/analyze_research_dataset.py \
  decision-evidence.jsonl \
  outcome-evidence.jsonl
```

The outcome model distinguishes target hits, stop hits and time exits. A profitable timeout does not inflate target-hit probability. The EV layer requires sample size, confidence width, validation calibration and positive ordinary plus conservative after-cost expectancy. It is research-only and cannot authorize a broker write.

See `docs/27_RESEARCH_EVIDENCE_AND_EV.md` for the full evidence lifecycle.

## Current validation

The v0.7.0 research/evidence head passed the full pre-release CI matrix before the release-identity update on Python 3.11 and Python 3.13:

- **319 tests passed**;
- **87.29% branch-aware coverage**;
- enforced coverage minimum: **85%**;
- critical Ruff checks passed;
- strict mypy checks passed for the deterministic Phase A-D/research contracts;
- dynamic package installation, bytecode compilation and `pip check` passed;
- secret-assignment scan passed;
- executed offline paper-order smoke passed on both Python versions.

A final CI run validates the exact v0.7.0 release identity before merge.

Software CI does **not** prove authenticated broker behavior or trading profitability. No real OANDA Practice success is claimed until the externally configured staged validation is actually run and its evidence is reviewed.

## Deliberate boundaries

The repository does not expose a live-money execution endpoint, fabricate centralized order flow from spot tick counts, substitute unlicensed scraping for production news/economic-calendar feeds, claim midpoint candle backtests equal executable quote history, or grant runtime authority to unvalidated scale-out/runner logic.

The next evidence milestone is authenticated OANDA Practice validation plus accumulation of a meaningful immutable decision/outcome dataset. That evidence should determine whether the remaining bottleneck is fundamental-data coverage, setup formation, market/execution conditions, portfolio constraints or actual strategy expectancy before strategy thresholds or management policy are changed.

For the detailed runtime boundary see `docs/16_IMPLEMENTATION_STATUS.md`; for OANDA setup see `docs/17_OANDA_PAPER_SETUP.md`; for campaign operations see `docs/25_PRACTICE_CAMPAIGN.md`; for calibration/EV research see `docs/27_RESEARCH_EVIDENCE_AND_EV.md`.
