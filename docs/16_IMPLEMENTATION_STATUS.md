# 16 — Implementation Status

## Current release

Version 0.7.23 is the current Practice-only FX research/execution platform. It preserves the structure-first strategy, independent risk authorization, broker-safe OANDA fxTrade Practice execution, point-in-time evidence, reconciliation controls, and research-validation framework from the v0.7 line while adding the first concrete external-data runtime layer from the post-v0.7.22 audit.

The system remains intentionally paper/Practice-only. No live-money endpoint is enabled, no new strategy received Practice authority in v0.7.23, and the presence of an adapter is not evidence that a licensed feed is connected or that a trading edge has been established.

```text
completed configured lower/higher candles + fresh broker quote
                              +
 point-in-time macro/news/calendar/cross-asset/flow inputs when configured
                              ↓
 supply/demand location + declared liquidity + sweep/reclaim
                              ↓
 pivot structure shift + retest/hold
                              ↓
 regime/policy selection + independent confirmation categories/sources
                              ↓
 structural stop/target + fundamental/cost/event admissibility
                              ↓
 independent portfolio risk authorization
                              ↓
 account lock + fresh size-aware quote + send-time revalidation
                              ↓
 priceBound + protected OANDA fxTrade Practice order
                              ↓
 reconciliation + protection verification + persistent uncertainty halt
                              ↓
 point-in-time decision evidence + campaign/outcome research
```

## Authority boundary

`config/system-policy-v0.7.json` is the machine-readable strategy authority manifest.

- Real-money execution is disabled.
- OANDA is restricted to `api-fxpractice.oanda.com` and `stream-fxpractice.oanda.com`.
- Broker writes require explicit paper mode, explicit write enablement, and reconciliation readiness.
- Unknown or ambiguous broker writes halt additional risk until reconciled.
- `sweep_reclaim:v1` remains the only Practice-authorized setup family.
- `zone_continuation:v1` and `breakout_retest:v1` remain shadow-only.
- `post_news_continuation:v1` remains shadow-only and requires independent institutional flow.
- `post_news_failure:v1` remains research-only and requires independent institutional flow.
- `flow_divergence:v1` and `vwap_repositioning:v1` are newly registered research-only families; registration does not grant signal-generation or broker authority.
- Broker tick activity is a local activity proxy and cannot count as institutional flow confirmation.
- Candidate quality score is not a calibrated win probability.
- LLM output cannot directly submit orders.

## Implemented technical/runtime foundation

The existing runtime continues to provide multi-timeframe structure, supply/demand zones, declared liquidity maps, sweep/reclaim detection, pivot-derived structure shifts, retest/hold lifecycle, structural stops/targets, DST-aware sessions, rollover handling, market-holiday blackouts, cost-aware admissibility, signed-correlation vetoes, gross and per-currency exposure controls, margin reserve, trailing drawdown/loss-streak/reserved-risk controls, protected Practice orders, price bounds, broker reconciliation, protection verification, emergency-close behavior, durable halts, point-in-time macro observations, historical replay/research datasets, ablations, calibration research, and campaign evidence.

OANDA integration remains Practice-only and includes account discovery/read-only operations, candles/history, pricing, metadata, positions, conversion, protected orders, reconciliation, and trade closing. Credentials remain environment-only and are never part of policy fingerprints or source control.

## v0.7.23 external-data runtime

The audit identified economic consensus, real news, cross-asset repricing, and centralized institutional flow as the largest operational information gaps. v0.7.23 adds concrete vendor-neutral runtime adapters for normalized JSON or tagged JSONL exports from those data planes.

### Economic calendar / consensus

`JsonEconomicCalendarProvider` supports:

- indicator metadata and directionality;
- pre-release point-in-time consensus and previously known values;
- release actuals and revisions with independent availability timestamps;
- scheduled events with `scheduled_at` separated from the timestamp at which the schedule became known;
- provider freshness/health.

Scheduled high-impact events from a configured calendar are merged into the existing `ScheduledMacroEvent` execution blackout path. Future schedule revisions are excluded. If the configured calendar cannot answer the scheduled-event query, evaluation fails closed rather than treating provider failure as proof that no event risk exists.

### News

`JsonNewsProvider` keeps `published_at` and `received_at` separate and uses provider receipt time as the point-in-time availability boundary. External decision evidence stores document identity, source, and timestamps without copying full licensed document bodies into the trace.

The adapter makes a licensed/operational news feed usable by the engine; it does not itself provide or license one, and v0.7.23 does not claim the complete event-classification/novelty/contradiction research stack has been validated on a live vendor stream.

### Cross-asset repricing

`JsonCrossAssetProvider` accepts timestamped, confidence-weighted signals normalized to the FX pair orientation. The resulting alignment can become an independent cross-asset confirmation with the true source IDs preserved in decision evidence.

Actual rates, rate-futures, equity/risk, volatility, commodity, broad-dollar, carry, and related feeds remain external runtime inputs that must be supplied and validated.

### Institutional order flow

`JsonOrderFlowProvider` accepts centralized/venue snapshots carrying raw delta, cumulative delta, VWAP, point of control, volume expansion, absorption, depth imbalance, normalized directional pressure, confidence, source, and observation time. Future observations are excluded and snapshots older than the configured ceiling fail closed.

Only a non-local external flow source with sufficient confidence and directionally aligned normalized pressure can add the independent FLOW confirmation category. `broker_tick_proxy` can no longer satisfy that category.

The repository still does not bundle CME or another licensed centralized feed, contract-roll mapping, or venue-specific aggregation. Those remain external data/validation work.

### Lineage and health

`ExternalContextAggregator` captures the exact external inputs available at the quote timestamp. `ExternalContextFusionPolicy` passes eligible cross-asset and institutional-flow evidence into the existing production fusion contract and stores source/time/health/error lineage in the candidate evidence.

The optional runtime paths are:

```text
FOREX_ECONOMIC_CALENDAR_PATH=
FOREX_NEWS_PATH=
FOREX_CROSS_ASSET_PATH=
FOREX_ORDER_FLOW_PATH=
FOREX_ORDER_FLOW_MAX_AGE_SECONDS=60
```

Licensed/vendor payloads should remain outside Git and be mounted/provisioned at runtime.

## Research/evidence integrity

The pre-existing research boundaries remain unchanged:

- quality scores are not win probabilities;
- future observations are excluded from point-in-time decisions;
- decision evidence is separated from later outcome labeling;
- mixed implementation/policy cohorts cannot silently merge;
- chronological train/validation/test or calibration/holdout boundaries remain mandatory where defined;
- after-cost expectancy, drawdown, calibration, ablation, replay reproducibility, and sustained Practice evidence—not code complexity—determine promotion.

The central-bank semantic workflow is methodologically advanced but still needs independent human calibration labels and a frozen acceptance threshold before the sealed holdout can be evaluated once. The repository must not infer those labels or claim semantic validity from code tests.

## Still evidence-gated or external after v0.7.23

The following are not represented as complete merely because the software can now ingest normalized inputs:

- licensed multi-country economic-calendar and true point-in-time consensus acquisition;
- licensed operational real-time news acquisition and live event-classification evidence;
- rates/rate-futures/equity/volatility/commodity/USD/carry cross-asset acquisition;
- CME/equivalent centralized FX futures flow, contract-roll/orientation mapping, and empirical validation of delta/CVD/absorption/profile/VWAP features;
- full signal state machines and prospective validation for research-only flow-divergence and VWAP-repositioning families;
- explicit macro-factor/event-cluster portfolio exposure limits beyond the current event blackout, currency concentration, correlation, margin, and stressed-risk controls;
- blinded human chart labeling for zone/sweep/structure validation;
- independent central-bank semantic calibration labels and one-time sealed-holdout evaluation;
- historical executable bid/ask/tick plus PIT macro/news/cross-asset/flow archives;
- sustained multi-session authenticated OANDA Practice evidence and hundreds of mature outcomes;
- evidence-backed promotion of shadow/research strategy or position-management policies;
- full production observability, provider/strategy/execution/risk dashboards, alerting, durable event backbone, and scaled deployment controls.

`config/audit-traceability-v0.7.23.json` is the machine-readable audit-to-code status matrix. `docs/49_V0_7_23_EXTERNAL_DATA_PLANE.md` documents the release boundary in detail.

## Validation boundary

CI compiles the project, checks dependency integrity and secret assignment, runs targeted Ruff and strict typing gates, executes the full pytest suite with branch-aware coverage, and performs an offline protected paper-order smoke on Python 3.11 and 3.13. The exact v0.7.23 head must pass those gates before merge.

Passing CI establishes software/invariant quality. It does not establish a profitable trading edge, a live licensed-data connection, or authenticated broker success.

## OANDA Practice sequence

When markets and deployment credentials permit, the correct evidence sequence remains:

```text
authenticated read-only account/pricing/candle/metadata check
-> transaction/state reconciliation
-> all-pair shadow campaign
-> separately gated broker-minimum protected open/verify/close round trip
-> capped Practice campaign
-> mature outcome labeling / ablation / after-cost analysis
```

No result from a closed-market weekend should be treated as representative execution evidence for a scalping system.
