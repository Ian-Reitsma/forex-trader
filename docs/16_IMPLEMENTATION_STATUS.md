# 16 — Implementation Status

## Current release

Version 0.6.1 is the hardened offline-simulation and OANDA fxTrade Practice platform. It contains the reconciled structure-first v0.6 runtime plus cohort-safe Practice evidence and fundamental-eligibility preflight. It remains intentionally Practice/paper-only and contains no live-money endpoint.

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
 eligible-universe preflight -> capped cohort-fingerprinted campaign
                              ↓
 cohort-safe fail-closed diagnosis + promotion metrics + stressed validation
```

## Implemented runtime components

- Supply/demand zones with proximal/distal bounds, departure strength, touches, penetration, freshness, invalidation and quality.
- Declared 5-p.m.-New-York prior-day liquidity, Sunday-5-p.m. prior-week liquidity, finalized Asia and London/New York opening ranges, equal highs/lows, external swings and round numbers.
- Source-time rules and expanded lower-history depth prevent self-created sweeps and truncated-session reconstruction.
- Pivot-derived structure plus explicit sweep -> shift -> retest/hold setup lifecycle, structural invalidation and structural/liquidity targets.
- Deployable lower M5/M10/M15/M30 and higher H1/H4 timeframe policy with bar-close signal timestamps.
- FVG/imbalance measurement remains research/confluence evidence only.
- DST-aware sessions, London fix/rollover handling and country/ECB-TARGET2 holiday blackouts.
- Spot tick count remains explicitly labeled a low-confidence activity proxy, not centralized footprint/delta.
- Immutable point-in-time macro observations, release revisions, component-specific decay, central-bank comparison, scheduled events and future-observation exclusion.
- Fundamentals are independent admissibility/conflict evidence; candidate quality is not a calibrated probability and does not use an arbitrary technical/fundamental percentage blend.
- SQLite decisions, execution claims, macro history, events, cost samples, broker transactions, durable cursors, persistent halts, FX risk-day state and account locks.
- OANDA Practice account discovery, candles/history, pricing, instrument metadata, positions, conversion, protected orders and trade closing.
- Broker metadata drives pip/display/unit/margin handling; size-aware pricing and worst-price `priceBound` are used before submission.
- Deterministic reject vs ambiguous-write classification, broker reconciliation, protection verification/repair, emergency-close handling and persistent uncertainty halts.
- Risk from lower(balance,NAV), currency conversion, 5-p.m.-New-York marked-loss latch, position/unit limits, gross/concentrated currency exposure, margin reserve and signed correlation veto.
- Learned session costs/slippage can tighten but never widen hard execution ceilings.
- Practice promotion gates require sustained multi-day/multi-instrument evidence and zero unresolved execution/risk halts.
- Backtest/replay supports gap stops, execution stress, MAE/MFE, ambiguity reporting, chronological holdouts and one globally deployable multi-pair threshold.
- Research-only management comparison has no runtime order authority.
- FastAPI, CLI, Docker and Python 3.11/3.13 CI.

## v0.6.1 Practice evidence hardening

Every newly generated campaign row includes a run-level `campaign_id`, secret-free deterministic `policy_fingerprint`, JSON-safe `policy_context` and campaign/universe metadata.

The fingerprint identifies outcome-affecting strategy, risk, timeframe, correlation, cost-model and campaign-execution configuration. Credentials and account IDs are excluded. Adaptive observed cost samples remain evidence within a cohort rather than forcing a new fingerprint every cycle.

Campaign analysis is cohort-safe:

- one policy fingerprint is analyzed at a time;
- mixed fingerprints fail unless `--policy-fingerprint` selects one explicitly;
- contradictory policy contexts inside one fingerprint fail;
- pre-fingerprint evidence remains the `legacy` cohort;
- impossible candidate/risk/order counts and inconsistent broker-status histograms fail;
- unresolved execution/provider/broker integrity problems outrank strategy tuning;
- new rejection semantics remain unclassified until mapped and tested.

When fundamentals are required, Practice-execution campaigns pre-filter pairs that cannot currently meet the configured fundamental-confidence gate. This avoids candle/pricing requests for guaranteed abstentions but cannot authorize a trade. Selected pairs still pass the complete quote-time engine. Shadow campaigns retain full-universe diagnostics by default; `--eligible-only` opts into preflight.

```bash
python scripts/run_practice_campaign.py --all-currency-pairs --max-cycles 1
python scripts/run_practice_campaign.py --all-currency-pairs --eligible-only --max-cycles 1
python scripts/analyze_campaign.py campaign-evidence.jsonl
python scripts/analyze_campaign.py campaign-evidence.jsonl --policy-fingerprint <fingerprint>
```

## Current automated validation

The exact v0.6.1 code/test head passed the complete CI matrix on Python 3.11 and Python 3.13:

- **238 tests passed**;
- **87.27% branch-aware coverage**;
- repository minimum coverage gate: **85%**;
- package installation and bytecode compilation passed;
- `pip check` dependency integrity passed;
- secret-assignment scan passed;
- executed offline paper-order smoke passed on both Python versions.

These checks establish software/invariant quality. They do not establish a profitable trading edge.

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

This environment does not expose `OANDA_API_TOKEN` / `OANDA_ACCOUNT_ID`; no real authenticated OANDA Practice round trip is claimed.

Once credentials are configured outside chat/Git, the required sequence is:

1. read-only Practice account/pricing/candle/instrument probe;
2. transaction synchronization/reconciliation;
3. broker currency-universe discovery;
4. all-pair shadow campaign and cohort analysis;
5. separately gated broker-minimum protected open -> verify -> close round trip;
6. capped Practice campaign starting with at most one new order per cycle;
7. same-policy cohort diagnosis before any threshold/timeframe/management change.

A changed policy must generate a new fingerprint so before/after evidence cannot be silently pooled.

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
