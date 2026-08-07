# 16 — Implementation Status

## Current release

Version 0.6.0 is the reconciled, functioning offline-simulation and OANDA fxTrade Practice platform. It restores the complete hardened audit-remediation tree and integrates the later evidence-first Practice campaign/analyzer. It remains intentionally Practice/paper-only and contains no live-money endpoint.

```text
completed configured lower/higher candles + executable depth-aware quote
                              +
 point-in-time macro/news/central-bank observations + market/event calendar
                              ↓
 location -> declared liquidity -> sweep -> structure shift -> retest/hold
                              ↓
 structural target + independent fundamental admissibility + execution-cost gate
                              ↓
 independent stop/currency/margin/correlation portfolio risk
                              ↓
 account lock -> fresh depth quote -> send-time revalidation -> priceBound
                              ↓
 protected Practice order / shadow trace
                              ↓
 broker reconciliation + protection verification + persistent uncertainty halt
                              ↓
 capped Practice campaign -> JSONL evidence -> fail-closed bottleneck diagnosis
                              ↓
 Practice promotion metrics + stressed walk-forward validation
```

## Implemented runtime components

- Supply/demand zones with proximal/distal bounds, impulsive departure measurement, touch count, penetration, freshness, invalidation and quality.
- Declared liquidity including 5-p.m.-New-York prior-day extremes, Sunday-5-p.m. prior-week extremes, finalized Asia highs/lows, finalized London/New York opening ranges, equal highs/lows, external swings and round-number references.
- Source-time rules prevent a bar from sweeping a level it just created; lower-timeframe history is expanded when needed so day/session liquidity is not reconstructed from truncated M5/M10 history.
- Pivot-derived market structure with EMA/RSI/ATR retained as secondary diagnostics rather than independent confirmation votes.
- Explicit sweep -> structure-shift -> retest/hold lifecycle, structural invalidation stop and nearest credible liquidity/opposing-zone target.
- Deployable timeframe policy matching research: lower M5/M10/M15/M30 and higher H1/H4. Completed-candle signals are timestamped at bar close, not OANDA bar start.
- Fair-value-gap detection with mitigation state and supply/demand overlap as a research/confluence feature only; FVG receives no automatic risk authority.
- DST-aware session phases including Asia, pre-London, London open/continuation, pre-New York, London/New York overlap, New York open/continuation, London fix and rollover.
- Conservative pair holiday blackouts using country calendars plus ECB/TARGET2. Context gates are checked both during initial evaluation and immediately before submission.
- Broker tick count/activity explicitly labeled as a low-confidence spot-FX activity proxy, not centralized footprint/delta or institutional order flow.
- Immutable point-in-time macro observations with exact availability timestamps, source metadata, forecasts/actuals/previous values, revision effects, news and central-bank material.
- Component-specific fundamental freshness/half-life behavior, central-bank statement comparison, directional negation/uncertainty handling and future-observation exclusion.
- Fundamentals operate as independent admissibility/conflict evidence; they are not mixed into technical quality with an arbitrary percentage. Candidate score is not represented as probability of profit.
- SQLite persistence for decisions, execution claims, macro history, scheduled events, execution-cost samples, broker transactions, durable cursors, persistent halts, FX risk-day state and account execution locks.
- OANDA Practice read-only account discovery, candles, bounded history, pricing, instrument metadata, positions, currency conversion, protected market orders and trade closing.
- Broker-metadata pip/display/unit precision and margin handling; exotic/non-JPY instruments do not rely on a two-case pip heuristic once provider metadata is loaded.
- Size-aware OANDA pricing buckets, worst-price `priceBound`, deterministic reject versus ambiguous-write classification and broker reconciliation before retry is considered.
- Dependent stop/take-profit verification after fill, repair attempt when absent, emergency-close attempt when protection cannot be verified and persistent execution halt for unresolved state.
- Risk sizing from lower(balance, NAV), quote-to-account currency conversion, 5-p.m.-New-York marked-loss latch, position/unit caps, gross currency exposure, single-currency concentration, margin reserve and signed correlation veto.
- Signed recent-return correlation can deny duplicated P/L risk and fails closed when existing risk cannot be evaluated; it never increases size.
- Learned session cost profiles and signed slippage samples. Learned limits may tighten but never widen configured spread/slippage ceilings.
- Practice promotion gates require sustained multi-day/multi-instrument evidence and zero unresolved execution/risk halts.
- Backtest/replay supports gap-through-stop losses, spread/slippage/decision-delay stress, MAE/MFE and ambiguous-bar frequency.
- Chronological rolling validation uses untouched final holdouts and one globally deployable multi-instrument threshold rather than pair-specific production thresholds.
- Research-only management comparison evaluates the structural single-target baseline against partial/breakeven-runner hypotheses without granting runtime authority.
- CLI, FastAPI, Docker and two-version GitHub Actions verification.

## Practice campaign and diagnosis

`PracticeCampaignRunner` is an evidence-collection layer; it does not bypass `TradingEngine` or loosen strategy/risk thresholds.

It provides:

- configured or broker-discovered currency-pair scanning;
- a strict maximum number of new Practice submissions per cycle;
- continued shadow evaluation after the order budget is spent;
- JSONL persistence of candidates, abstentions, risk denials, errors, promotion state and every broker status;
- immediate cycle stop on unresolved order states including created/acknowledged/partial/unknown/reconciliation-required/closing/emergency-close;
- explicit reject/cancel accounting;
- a fail-closed campaign analyzer that classifies provider, execution, broker, fundamental-data, market-context, strategy-formation and portfolio-risk bottlenecks;
- unclassified future rejection codes remain unclassified until mapped/tested rather than silently becoming a clean result;
- backward-compatible parsing of older campaign JSONL that predates the generalized unresolved counter.

Operator commands:

```bash
python scripts/run_practice_campaign.py --all-currency-pairs --max-cycles 1
python scripts/analyze_campaign.py campaign-evidence.jsonl
```

## Current automated validation

The exact reconciled v0.6 integration head passed the complete CI matrix on Python 3.11 and Python 3.13:

- **222 tests passed**;
- **87.02% branch-aware coverage**;
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

Runtime timeframe selection is explicit:

```dotenv
FOREX_LOWER_TIMEFRAME=M15
FOREX_HIGHER_TIMEFRAME=H4
```

Only combinations represented by the research grid are accepted. `--technical-only` on research scripts is diagnostic comparison only when point-in-time macro history is unavailable.

## Authenticated OANDA Practice boundary

This execution environment does not currently expose `OANDA_API_TOKEN` / `OANDA_ACCOUNT_ID`, so a real authenticated OANDA Practice round trip is **not** claimed.

Once credentials are configured outside chat/Git, the required sequence is:

1. read-only Practice account/pricing/candle/instrument probe;
2. broker transaction synchronization/reconciliation;
3. real broker currency-universe discovery;
4. one-cycle all-pair shadow campaign;
5. separately gated broker-minimum protected open -> protection verification -> close round trip;
6. capped Practice execution campaign (start with at most one new order per cycle);
7. analyze accumulated campaign evidence before changing thresholds or management policy.

Secrets must never be pasted into chat or committed to Git.

## Still incomplete / evidence-gated

- Automated licensed economic-calendar collection and consensus snapshots. Scheduled events can already be persisted/enforced once a legitimate feed/import supplies them.
- Automated licensed news ingestion and official central-bank document collection.
- True centralized futures/order-flow ingestion (CME or another legitimate centralized proxy). Spot broker tick activity remains explicitly non-equivalent.
- Historical executable bid/ask/tick reconstruction for every research period; midpoint-candle research can stress assumptions but cannot invent absent quote history.
- Evidence-backed runtime partial-profit/runner/trailing management. Management alternatives remain research-only until after-cost out-of-sample evidence supports them.
- Sufficient multi-regime, multi-pair untouched historical and sustained authenticated OANDA Practice evidence to claim positive expectancy.
- PostgreSQL/TimescaleDB/event-bus topology for significantly higher-volume deployment.
- Any live-money execution mode.

No win-rate, profitability or capital-readiness claim is supported until the combined system has sufficient point-in-time data, untouched out-of-sample validation and sustained authenticated Practice evidence.
