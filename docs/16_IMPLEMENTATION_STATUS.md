# 16 — Implementation Status

## Current release

Version 0.7.0 is the hardened offline-simulation and OANDA fxTrade Practice research/execution platform. It contains the structure-first runtime, Phase 0 authority manifest, Phase A-D information/strategy/research/execution contracts, durable reconciliation readiness, independent confirmation evidence, cohort-safe Practice evidence, point-in-time per-decision research evidence, conservative outcome labeling, chronological calibration and a research-only expected-value gate. It remains intentionally Practice/paper-only and contains no live-money endpoint.

```text
completed configured lower/higher candles + depth-aware quote
                              +
 point-in-time macro/news/central-bank observations + events/holidays
                              +
 regime + cross-asset/flow provider readiness
                              ↓
 location -> declared liquidity -> sweep -> structure shift -> retest/hold
                              ↓
 strategy policy authority + independent confirmation categories/sources
                              ↓
 structural target + independent fundamental admissibility + cost gate
                              ↓
 independent stop/currency/margin/correlation/drawdown portfolio risk
                              ↓
 account lock -> fresh depth quote -> send-time revalidation -> priceBound
                              ↓
 protected Practice order / shadow trace
                              ↓
 reconciliation + protection verification + persistent uncertainty halt
                              ↓
 aggregate campaign evidence + detailed point-in-time decision evidence
                              ↓
 mature outcome labeling -> cohort calibration -> conservative research EV
```

## Phase 0 authority boundary

`config/system-policy-v0.7.json` is the machine-readable system authority manifest.

- Real-money execution is disabled.
- OANDA is restricted to fxTrade Practice hosts.
- Broker writes require durable reconciliation readiness.
- Unknown/ambiguous write state halts additional risk until reconciled.
- `sweep_reclaim:v1` is the only Practice-authorized setup family.
- Zone continuation and breakout/retest remain shadow-only.
- Post-news continuation remains shadow-only and requires real institutional flow.
- Post-news failure remains research-only.
- Broker tick activity cannot be relabeled as institutional flow.
- Candidate quality score is not a win probability.
- LLM output cannot directly submit orders.

## Implemented runtime components

- Supply/demand zones with proximal/distal bounds, departure strength, touches, penetration, freshness, invalidation and quality.
- Raw zone-research features for departure speed, imbalance, flow alignment, retests, penetration, age, time-in-zone, renewed displacement, higher-timeframe alignment, liquidity proximity and event origin.
- Declared 5-p.m.-New-York prior-day liquidity, Sunday-5-p.m. prior-week liquidity, finalized Asia and London/New York opening ranges, equal highs/lows, external swings and round numbers.
- Source-time rules and expanded lower-history depth prevent self-created sweeps and truncated-session reconstruction.
- Pivot-derived structure plus explicit sweep -> shift -> retest/hold setup lifecycle, structural invalidation and structural/liquidity targets.
- Deterministic persisted setup lifecycle with observing/context/location/catalyst/confirmation/candidate and rejected/expired/invalidated states.
- Deployable lower M5/M10/M15/M30 and higher H1/H4 timeframe policy with bar-close signal timestamps.
- Evaluation-local completed-candle reuse can satisfy smaller same-instrument/same-granularity requests from a larger already-fetched snapshot inside one `FxTradingEngine.evaluate()` call. Quotes are never cached and snapshots do not survive the evaluation.
- FVG/imbalance measurement remains research/confluence evidence only.
- DST-aware sessions, London fix/rollover handling and country/ECB-TARGET2 holiday blackouts.
- Regime classification for trend, range, transition, pre-event, post-event impulse, post-event normalized, disorderly and rollover context.
- Versioned strategy-policy selection with explicit Practice/shadow/research authority.
- Independent confirmation categories: price, fundamentals, flow, cross-asset and execution. Minimum category and source counts are separate requirements.
- Spot tick count remains explicitly labeled a low-confidence local activity proxy, not centralized footprint/delta.
- Provider interfaces exist for licensed economic calendars, official documents, news, cross-assets and institutional flow. Unconfigured providers are represented as unavailable rather than fabricated.
- Immutable point-in-time macro observations, release consensus/actual/revision semantics, component-specific decay, horizon-specific currency context, central-bank comparison, scheduled events and future-observation exclusion.
- Fundamentals are independent admissibility/conflict evidence; candidate quality is not a calibrated probability and does not use an arbitrary technical/fundamental percentage blend.
- SQLite decisions, execution claims, macro history, events, cost samples, broker transactions, durable cursors, persistent halts, reconciliation readiness, advanced setup/risk state, FX risk-day state and account locks.
- OANDA Practice account discovery, candles/history, pricing, instrument metadata, positions, conversion, protected orders and trade closing.
- Broker metadata drives pip/display/unit/margin handling; size-aware pricing and worst-price `priceBound` are used before submission.
- Deterministic reject vs ambiguous-write classification, broker reconciliation, protection verification/repair, emergency-close handling and persistent uncertainty halts.
- Broker-minimum Practice round-trip validation always attempts to close a known filled probe trade even when protection verification fails or raises; failed/unverifiable closes are critical stop conditions.
- Risk from lower(balance,NAV), broker-priced currency conversion, 5-p.m.-New-York marked-loss latch, position/unit limits, gross/concentrated currency exposure, margin reserve, signed correlation veto, trailing drawdown, loss streak, reserved risk and gap-stress maximum loss.
- Risk authorization records candidate/environment identity, approved size/direction/entry range/stop, stressed loss, portfolio snapshot, consumed limits, policy version and an integrity digest.
- Learned session costs/slippage can tighten but never widen hard execution ceilings.
- Research order contracts cover market, limit, stop and market-if-touched semantics without silently approximating unsupported broker behavior.
- Research-only position management can emit HOLD, REDUCE, MOVE_PROTECTION or CLOSE; it cannot widen the original stop and has no automatic Practice authority.
- FastAPI, CLI, Docker and Python 3.11/3.13 CI.

## Practice evidence integrity

Every aggregate campaign row includes a run-level `campaign_id`, secret-free deterministic `policy_fingerprint`, JSON-safe `policy_context` and campaign/universe metadata.

The fingerprint identifies outcome-affecting strategy, risk, timeframe, correlation, cost-model, campaign-execution configuration, implementation semantic version and exact build revision when available. Credentials and account IDs are never fingerprint inputs.

Campaign analysis remains cohort-safe:

- one policy fingerprint is analyzed at a time;
- mixed fingerprints fail unless one is explicitly selected;
- contradictory contexts inside a fingerprint fail;
- pre-fingerprint evidence remains the `legacy` cohort;
- impossible candidate/risk/order counts and inconsistent broker-status histograms fail;
- unresolved execution/provider/broker integrity problems outrank strategy tuning;
- new rejection semantics remain unclassified until mapped and tested.

## Detailed decision evidence and outcome labeling

Campaigns may additionally persist one point-in-time JSONL row per instrument attempt. These records contain immutable campaign/policy identity, setup/regime/session, independent confirmation categories/source IDs, score components, entry/stop/target geometry, captured quote, risk/order state, raw candidate evidence and evaluation errors.

Decision evidence contains no future outcome. `scripts/label_decision_evidence.py` later fetches historical OANDA Practice-market candles read-only and writes a separate outcome evidence stream once the path is mature.

Labeling is conservative:

- same-candle stop/target ambiguity assumes stop first;
- captured decision-time spread can be included;
- entry/exit slippage stress is explicit;
- terminal target/stop can resolve before the full horizon;
- a timeout is not written until the complete configured horizon exists.

Decision/outcome joins fail on identity mismatches or mixed policy fingerprints rather than silently combining incompatible software/strategy cohorts.

## Probability and EV semantics

The empirical model has three explicit path outcomes: target before stop, stop before target, and time exit. Positive time exits are not target hits; losing time exits are not stop hits. Timeout probability and empirical timeout R enter expected value separately.

With no observations the prior remains neutral at 50% target / 50% stop / 0% timeout. Once observed outcomes exist, all three paths are regularized independently.

Cohort probability hierarchy defaults to setup + regime + session, falling back through setup + regime, setup and all eligible history when a cohort is sparse. Instrument-specific cohorts are optional and must still meet sample requirements.

Research data is split chronologically into train, validation and untouched test folds. Validation measures target-event Brier score and expected calibration error. The test fold is never used to fit its own probability or calibration threshold.

The research EV gate requires minimum sample size, bounded probability confidence width, bounded validation calibration error, positive ordinary after-cost EV and positive conservative lower-bound EV. Costs include captured spread, historical execution/slippage, adverse-selection allowance and operational uncertainty. The gate has no broker authority and cannot replace policy authority, risk authorization, reconciliation or Practice promotion.

See `docs/27_RESEARCH_EVIDENCE_AND_EV.md`.

## Implementation identity

`forex_trader.__version__` is the authoritative semantic version. Setuptools derives installed distribution metadata from it, FastAPI/OpenAPI exposes the same value, and campaign policy fingerprints include the implementation version.

Campaign context also includes an exact source revision from `FOREX_BUILD_REVISION`, falling back to `GITHUB_SHA` in GitHub Actions. Local operators should set:

```bash
export FOREX_BUILD_REVISION="$(git rev-parse HEAD)"
```

The manual OANDA Practice workflow sets it to the exact workflow SHA automatically.

## Current automated validation

The pre-release v0.7 research/evidence head passed the complete Python 3.11 and Python 3.13 CI matrix before the final semantic-version/docs commit:

- **319 tests passed** on each Python version;
- **87.29% branch-aware coverage**;
- repository minimum coverage gate: **85%**;
- critical Ruff checks passed;
- strict mypy checks passed across the deterministic Phase A-D/research modules;
- bytecode compilation and `pip check` dependency integrity passed;
- secret-assignment scan passed;
- executed offline protected paper-order smoke passed on both Python versions.

The exact v0.7.0 release identity is revalidated by the final CI run before merge.

These checks establish software/invariant quality. They do not establish a profitable trading edge or authenticated broker success.

## Research/operator commands

```bash
forex-trader sync
forex-trader sync --stream --max-events 100
forex-trader promotion
python scripts/import_macro_history.py history.jsonl
python scripts/backtest_oanda.py --instrument EUR_USD --days 90
python scripts/optimize_oanda.py --instrument EUR_USD --days 180
python scripts/validate_oanda.py --instruments EUR_USD,GBP_USD,USD_JPY --days 180
python scripts/compare_management_oanda.py --instrument EUR_USD --days 180
python scripts/run_practice_campaign.py \
  --all-currency-pairs --max-cycles 1 \
  --evidence-path campaign-evidence.jsonl \
  --decision-evidence-path decision-evidence.jsonl
python scripts/analyze_campaign.py campaign-evidence.jsonl
python scripts/label_decision_evidence.py decision-evidence.jsonl --output outcome-evidence.jsonl
python scripts/analyze_research_dataset.py decision-evidence.jsonl outcome-evidence.jsonl
```

## Authenticated OANDA Practice boundary

The repository never stores OANDA credentials and does not infer authenticated success from CI. Local runtime or GitHub Actions must receive credentials externally.

The manual `OANDA Practice Validation` workflow implements three ordered stages from `main`:

1. `read-only` — requires `OANDA_API_TOKEN`; explicit account ID is optional because the adapter can discover an authorized Practice account. It runs the authenticated probe, transaction sync, one-cycle all-pair shadow campaign and analyzer, and now captures detailed shadow decision evidence.
2. `round-trip` — additionally requires explicit `OANDA_ACCOUNT_ID` and `confirm_practice_write=true`. It repeats the software/read-only gates, executes the broker-minimum protected open -> verify -> close probe, then reconciles broker state again.
3. `campaign` — only after those gates, runs the capped all-pair Practice campaign, aggregate analyzer and promotion report, while also capturing detailed Practice decision evidence. Initial operation should remain at one new order per cycle.

Authenticated Practice evidence—not software confidence—must determine whether the next bottleneck is data coverage, setup formation frequency, execution conditions, portfolio constraints or actual strategy expectancy.

## Still evidence-gated / external

- Authenticated OANDA Practice evidence remains blocked until deployment supplies the required Actions/local credentials.
- Automated licensed economic-calendar/point-in-time consensus collection.
- Automated licensed news and official central-bank document ingestion.
- Real cross-asset repricing feeds for rates, futures, equities and relevant commodities.
- True centralized futures/order-flow data such as CME; spot tick activity is not equivalent.
- Historical executable bid/ask/tick archives for all research periods.
- Runtime partial-profit/runner/trailing management until after-cost untouched evidence supports it.
- Promotion of zone continuation/breakout-retest beyond shadow authority.
- Sufficient multi-regime untouched history and sustained authenticated Practice evidence to claim positive expectancy.
- Higher-volume PostgreSQL/TimescaleDB/event-bus deployment.
