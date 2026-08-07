# 16 — Implementation Status

## Current release

Version 0.6.4 is the hardened offline-simulation and OANDA fxTrade Practice platform. It contains the reconciled structure-first runtime, cohort-safe Practice evidence, fundamental-eligibility preflight, implementation-bound evidence identity, evaluation-local completed-candle reuse, a fail-closed broker-minimum round-trip helper, and an operator-driven staged Practice-validation workflow. It remains intentionally Practice/paper-only and contains no live-money endpoint.

```text
completed configured lower/higher candles + depth-aware quote
                              +
 point-in-time macro/news/central-bank observations + events/holidays
                              ↓
 location -> declared liquidity -> sweep -> structure shift -> retest/hold
                              ↓
 structural target + independent fundamental admissibility + cost gate
                              ↓
 independent stop/currency/margin/correlation portfolio risk
                              ↓
 account lock -> fresh depth quote -> send-time revalidation -> priceBound
                              ↓
 protected Practice order / shadow trace
                              ↓
 reconciliation + protection verification + persistent uncertainty halt
                              ↓
 eligible-universe preflight -> implementation-bound cohort campaign
                              ↓
 cohort-safe fail-closed diagnosis + promotion metrics + stressed validation
```

## Implemented runtime components

- Supply/demand zones with proximal/distal bounds, departure strength, touches, penetration, freshness, invalidation and quality.
- Declared 5-p.m.-New-York prior-day liquidity, Sunday-5-p.m. prior-week liquidity, finalized Asia and London/New York opening ranges, equal highs/lows, external swings and round numbers.
- Source-time rules and expanded lower-history depth prevent self-created sweeps and truncated-session reconstruction.
- Pivot-derived structure plus explicit sweep -> shift -> retest/hold setup lifecycle, structural invalidation and structural/liquidity targets.
- Deployable lower M5/M10/M15/M30 and higher H1/H4 timeframe policy with bar-close signal timestamps.
- Evaluation-local completed-candle reuse can satisfy smaller same-instrument/same-granularity requests from a larger already-fetched snapshot inside one `FxTradingEngine.evaluate()` call. Quotes are never cached and snapshots do not survive the evaluation.
- FVG/imbalance measurement remains research/confluence evidence only.
- DST-aware sessions, London fix/rollover handling and country/ECB-TARGET2 holiday blackouts.
- Spot tick count remains explicitly labeled a low-confidence activity proxy, not centralized footprint/delta.
- Immutable point-in-time macro observations, release revisions, component-specific decay, central-bank comparison, scheduled events and future-observation exclusion.
- Fundamentals are independent admissibility/conflict evidence; candidate quality is not a calibrated probability and does not use an arbitrary technical/fundamental percentage blend.
- SQLite decisions, execution claims, macro history, events, cost samples, broker transactions, durable cursors, persistent halts, FX risk-day state and account locks.
- OANDA Practice account discovery, candles/history, pricing, instrument metadata, positions, conversion, protected orders and trade closing.
- Broker metadata drives pip/display/unit/margin handling; size-aware pricing and worst-price `priceBound` are used before submission.
- Deterministic reject vs ambiguous-write classification, broker reconciliation, protection verification/repair, emergency-close handling and persistent uncertainty halts.
- Broker-minimum Practice round-trip validation is refactored into a testable helper that always attempts to close a known filled probe trade even when protection verification fails or raises; failed/unverifiable closes are critical stop conditions.
- Risk from lower(balance,NAV), broker-priced currency conversion, 5-p.m.-New-York marked-loss latch, position/unit limits, gross/concentrated currency exposure, margin reserve and signed correlation veto.
- Learned session costs/slippage can tighten but never widen hard execution ceilings.
- Practice promotion gates require sustained multi-day/multi-instrument evidence and zero unresolved execution/risk halts.
- Backtest/replay supports gap stops, execution stress, MAE/MFE, ambiguity reporting, chronological holdouts and one globally deployable multi-pair threshold.
- Research-only management comparison has no runtime order authority.
- FastAPI, CLI, Docker and Python 3.11/3.13 CI.

## Practice evidence integrity

Every newly generated campaign row includes a run-level `campaign_id`, secret-free deterministic `policy_fingerprint`, JSON-safe `policy_context` and campaign/universe metadata.

The fingerprint identifies outcome-affecting strategy, risk, timeframe, correlation, cost-model and campaign-execution configuration. Practice-execution campaigns can pre-filter pairs guaranteed to fail the required fundamental-confidence gate, saving candle/pricing requests without authorizing any trade. Shadow mode keeps full-universe diagnostics by default.

Campaign analysis is cohort-safe:

- one policy fingerprint is analyzed at a time;
- mixed fingerprints fail unless `--policy-fingerprint` explicitly selects one;
- contradictory contexts inside a fingerprint fail;
- pre-fingerprint evidence remains the `legacy` cohort;
- impossible candidate/risk/order counts and inconsistent broker-status histograms fail;
- unresolved execution/provider/broker integrity problems outrank strategy tuning;
- new rejection semantics remain unclassified until mapped and tested.

## v0.6.4 implementation identity

`forex_trader.__version__` is the authoritative semantic version. Setuptools derives installed distribution metadata from it, and FastAPI/OpenAPI exposes the same value. This removes package/runtime/API version drift.

Campaign policy context includes:

- `implementation.version` — the semantic runtime/package version;
- `implementation.build_revision` — optional immutable source revision from `FOREX_BUILD_REVISION`, otherwise `GITHUB_SHA` when available.

Implementation version/revision participates in the policy fingerprint, so otherwise-identical configuration from different software builds cannot silently share an evidence cohort. Credentials and account IDs are not included.

For local Git campaigns, operators should set:

```bash
export FOREX_BUILD_REVISION="$(git rev-parse HEAD)"
```

The manual OANDA Practice workflow sets `FOREX_BUILD_REVISION` to the exact GitHub workflow SHA automatically.

## Current automated validation

The exact v0.6.4 code/test head passed the complete CI matrix on Python 3.11 and Python 3.13:

- **264 tests passed** on each Python version;
- **87.37% branch-aware coverage**;
- repository minimum coverage gate: **85%**;
- fresh dynamic package installation as `forex-trader==0.6.4` passed;
- bytecode compilation and `pip check` dependency integrity passed;
- secret-assignment scan passed;
- executed offline paper-order smoke passed on both Python versions.

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
python scripts/run_practice_campaign.py --all-currency-pairs --max-cycles 1
python scripts/analyze_campaign.py campaign-evidence.jsonl
```

## Authenticated OANDA Practice boundary

The repository never stores OANDA credentials and does not infer authenticated success from CI. Local runtime or GitHub Actions must receive credentials externally.

The manual `OANDA Practice Validation` workflow implements three ordered stages from `main`:

1. `read-only` — requires `OANDA_API_TOKEN`; explicit account ID is optional because the adapter can discover an authorized Practice account. It runs the authenticated probe, transaction sync, one-cycle all-pair shadow campaign and analyzer.
2. `round-trip` — additionally requires explicit `OANDA_ACCOUNT_ID` and `confirm_practice_write=true`. It repeats the software/read-only gates, executes the broker-minimum protected open -> verify -> close probe, then reconciles broker state again.
3. `campaign` — only after those gates, runs the capped all-pair Practice campaign, analyzer and promotion report. Initial operation should remain at one new order per cycle.

Authenticated Practice evidence—not software confidence—must determine whether the next bottleneck is data coverage, setup formation frequency, execution conditions, portfolio constraints or actual strategy expectancy. A changed policy or implementation generates a new fingerprint so before/after evidence cannot be silently pooled.

## Still evidence-gated

- Automated licensed economic-calendar/consensus collection.
- Automated licensed news and official central-bank document ingestion.
- True centralized futures/order-flow data such as CME; spot tick activity is not equivalent.
- Historical executable bid/ask/tick archives for all research periods.
- Runtime partial-profit/runner/trailing management until after-cost untouched evidence supports it.
- Sufficient multi-regime untouched history and sustained authenticated Practice evidence to claim positive expectancy.
- Higher-volume PostgreSQL/TimescaleDB/event-bus deployment.
- Any live-money execution mode.

No win-rate, profitability or capital-readiness claim is supported until point-in-time data, untouched out-of-sample validation and sustained authenticated Practice evidence exist.
