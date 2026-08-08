# 16 — Implementation Status

## Current release

Version 0.7.25 is the current Practice-only FX research/execution platform. It includes the v0.7.23 point-in-time external-data runtime, the v0.7.24 macro-factor risk and blinded technical-validation tranche, and the v0.7.25 durable operational telemetry/control-plane tranche.

The system remains intentionally paper/Practice-only. OANDA is restricted to fxTrade Practice endpoints. `sweep_reclaim:v1` remains the only Practice-authorized strategy family. Research strategies, annotation outputs, telemetry, model outputs, and LLM outputs cannot directly authorize or submit orders.

```text
completed multi-timeframe candles + fresh broker quote
                              +
PIT macro/news/calendar/cross-asset/centralized-flow inputs when configured
                              ↓
location + liquidity + sweep/reclaim + structure shift + retest
                              ↓
regime/policy selection + independent evidence categories/sources
                              ↓
fundamental/cost/event admissibility + stop/target geometry
                              ↓
stop risk + currency exposure + signed correlation + macro-factor concentration
+ drawdown/loss-streak/reserved-risk/gap-stress authorization
                              ↓
account lock + fresh size-aware quote + send-time revalidation
                              ↓
protected OANDA fxTrade Practice order
                              ↓
reconciliation + protection verification + persistent uncertainty halt
                              ↓
durable decision/risk/execution/provider/halt/readiness telemetry
```

## Authority boundary

`config/system-policy-v0.7.json` is the machine-readable authority manifest.

- Real-money execution is disabled.
- OANDA REST/stream hosts are restricted to the fxTrade Practice environment.
- Broker writes require paper mode, explicit write enablement, and reconciliation readiness.
- Unknown/ambiguous writes halt new risk until reconciled.
- `sweep_reclaim:v1` is the only Practice-authorized strategy family.
- Zone continuation and breakout/retest remain shadow-only.
- Post-news, flow-divergence, and centralized-VWAP strategies remain shadow/research gated as declared.
- Broker tick activity cannot satisfy institutional-flow confirmation.
- Operational telemetry is observational only and cannot grant risk, clear halts, change strategy authority, or submit orders.

## Implemented decision and execution runtime

The runtime includes:

- multi-timeframe structure/location/liquidity/sweep/reclaim/retest logic;
- DST-aware sessions, event/holiday blackouts, and rollover restrictions;
- point-in-time macro observations and future-data exclusion;
- provider-neutral PIT adapters for economic consensus/actuals/schedules, news receipt time, cross-asset repricing, and centralized flow;
- independent evidence categories/sources and broker tick-proxy separation;
- broker metadata, size-aware quotes, price bounds, protected Practice orders, reconciliation, protection verification/repair, and uncertainty halts;
- lower(balance,NAV) sizing, daily loss, currency exposure, margin reserve, signed-correlation veto, trailing drawdown, loss streak, reserved/pending risk, gap stress, and explicit macro-factor concentration;
- cohort-safe campaign identity, PIT decision evidence, outcome labeling, calibration, ablation, and conservative research EV tooling.

## v0.7.24 validation/risk additions

The initial macro-factor guard classifies the audited ten-pair universe into deterministic macro/rates/commodity policy clusters and limits gross account-currency notional by shared factor independently from rolling correlation. Strict mode fails closed for unclassified or unpriceable exposures. The default 2.5×-capital factor ceiling is an initial software policy value, not an empirically optimized claim.

The blinded technical-ground-truth workflow exports raw completed OHLCV windows only, requires at least two independent reviewers, requires independent adjudication on disagreement, and fixes a chronological 2/3 calibration + 1/3 holdout split. Actual expert labels are still external evidence and cannot be replaced by CI or model self-labeling.

Flow-divergence and centralized-VWAP repositioning have explicit research state machines but no execution path. Their research signals expose `executable=False` by construction and still require real centralized-flow data plus historical/prospective validation.

See `docs/50_V0_7_24_RISK_AND_TECHNICAL_VALIDATION.md`.

## v0.7.25 durable operational telemetry

The authoritative trading repository now also persists operational events derived from the same evidence used by the decision/execution path. Trace-derived event IDs are deterministic so repeated persistence of one trace enriches rather than double-counts its operational record.

The event stream records decision disposition/rejection, selected policy/regime, risk grants/denials and veto reasons, execution status/protection state, external-provider health/rate limiting/runtime errors, persistent halts, and broker reconciliation readiness.

`OperationalTelemetryService` produces bounded-window summaries for:

- decision and rejection concentration;
- strategy/regime mix;
- risk grant/denial and veto concentration;
- broker execution status;
- provider health;
- active halts and not-ready accounts;
- deterministic operational alerts.

Initial critical alerts cover active halts, reconciliation-not-ready accounts, unresolved/emergency execution state, and unavailable providers. Provider runtime/evaluation errors are errors; provider degradation/rate limiting are warnings.

Protected observational endpoints:

```text
GET /v1/operations/summary
GET /v1/operations/events
GET /v1/operations/metrics
```

The metrics endpoint exposes Prometheus-compatible operational counters/gauges. External collection, dashboards, paging/escalation, retention/downsampling, and multi-host event transport remain deployment work.

See `docs/51_V0_7_25_OPERATIONAL_TELEMETRY.md`.

## Research/evidence integrity

The repository continues to enforce these distinctions:

- candidate quality is not a win probability;
- point-in-time decisions exclude future observations;
- decision evidence and future outcome evidence are separate;
- campaign fingerprints change when outcome-affecting strategy/risk/software identity changes;
- technical and central-bank human validation requires independent labels;
- calibration/validation/holdout boundaries are chronological and explicit;
- promotion requires after-cost expectancy, drawdown, calibration, ablation/attribution, replay reproducibility, sample sufficiency, and sustained Practice evidence.

## Still external/evidence-gated

The audit is not fully closed. Remaining external/evidence requirements include:

- licensed multi-country economic-calendar and true PIT consensus acquisition;
- licensed real-time news and prospective event-classification evidence;
- rates/rate-futures/equity/volatility/commodity/USD/carry cross-asset feeds;
- CME/equivalent centralized FX futures/order-flow data and contract-roll/orientation mapping;
- real expert labels for the blinded technical corpus;
- independent central-bank calibration labels and one sealed holdout evaluation;
- historical executable bid/ask/tick plus PIT macro/news/cross-asset/flow archives;
- empirical calibration of macro-factor taxonomy/limits;
- sustained multi-session authenticated OANDA Practice evidence;
- external dashboards, alert routing, retention/downsampling, deployment SLOs, backup/restore and failover drills;
- distributed/scale-out storage/event transport if future deployment volume requires it.

## Validation boundary

The standard CI runs compilation, dependency integrity, secret scanning, critical Ruff, strict typing, full pytest with branch-aware coverage, and an offline protected-paper smoke on Python 3.11 and 3.13. The v0.7.24 risk/validation gate and annotation-integrity workflow remain active. v0.7.25 adds a separate Python 3.11/3.13 operations gate for the telemetry domain/service and focused repository/API behavior.

Passing software CI establishes implementation/invariant quality. It does not establish a profitable edge, live licensed-feed operation, or authenticated broker success.

## OANDA Practice evidence sequence

The current development date is Saturday, August 8, 2026, when the FX market is closed. Representative execution evidence is therefore not being manufactured from stale weekend conditions.

When the market is open and the runtime can reach OANDA Practice, the next sequence remains:

```text
authenticated read-only account/pricing/candle/metadata probe
-> transaction/state reconciliation
-> all-pair shadow campaign
-> separately gated protected broker-minimum open/verify/close round trip
-> capped Practice campaign
-> mature outcome labeling, attribution and after-cost analysis
```

See `config/audit-traceability-v0.7.25.json` for requirement-by-requirement status.
