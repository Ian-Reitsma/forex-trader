# 16 — Implementation Status

## Current release

Version 0.7.24 is the current Practice-only FX research/execution platform. It preserves the v0.7.23 point-in-time external-data runtime while closing three additional audit gaps: explicit macro-factor concentration risk, blinded technical human-ground-truth infrastructure, and concrete research-only flow-divergence/VWAP state machines.

The system remains intentionally paper/Practice-only. OANDA is still restricted to fxTrade Practice endpoints. `sweep_reclaim:v1` remains the only Practice-authorized strategy family. No research strategy, annotation output, model output, or LLM output can directly submit an order.

```text
completed lower/higher candles + fresh broker quote
                              +
 point-in-time macro/news/calendar/cross-asset/centralized-flow inputs when configured
                              ↓
 location + liquidity + sweep/reclaim + structure shift + retest
                              ↓
 regime/policy selection + independent evidence categories/sources
                              ↓
 stop/target + fundamental/cost/event admissibility
                              ↓
 currency exposure + return correlation + explicit macro-factor concentration
                              +
 drawdown/loss-streak/reserved-risk/gap-stress authorization
                              ↓
 account lock + size-aware quote + send-time revalidation
                              ↓
 protected OANDA fxTrade Practice order
                              ↓
 reconciliation + protection verification + persistent uncertainty halt
```

## Authority boundary

`config/system-policy-v0.7.json` is the machine-readable authority manifest.

- Real-money execution is disabled.
- OANDA hosts are restricted to `api-fxpractice.oanda.com` and `stream-fxpractice.oanda.com`.
- Broker writes require paper mode, explicit paper-write enablement, and reconciliation readiness.
- Unknown/ambiguous broker writes halt new risk until reconciled.
- `sweep_reclaim:v1` remains the only Practice-authorized family.
- `zone_continuation:v1` and `breakout_retest:v1` remain shadow-only.
- Post-news families remain shadow/research gated and require genuine external institutional flow where declared.
- `flow_divergence:v1` and `vwap_repositioning:v1` now have concrete research state evaluators but remain research-only. Their signal objects expose `executable=False` by construction.
- Broker tick activity remains a local activity proxy and cannot satisfy institutional FLOW confirmation.
- Blinded technical annotations are research truth data only and have no broker-authority path.

## v0.7.24 macro-factor concentration risk

The risk layer now includes `MacroFactorClusterGuard`, which is independent from return correlation and ordinary currency-leg exposure. Its purpose is to stop a portfolio from accumulating multiple pairs that are all expressions of the same scheduled-macro/rates thesis simply because recent pairwise correlations are temporarily low.

The initial policy taxonomy covers the ten audited FX pairs and assigns deterministic factors such as `usd_macro`, `usd_rates`, `eur_rates`, `jpy_rates`, and `commodity_cycle`. These tags are policy classifications, not estimated statistical betas.

For every proposed position the guard:

- prices the candidate and all existing positions in account-currency gross notional;
- accumulates each instrument's notional into every declared macro-factor bucket;
- compares each factor against an independent capital-relative ceiling;
- fails closed when an instrument is unclassified under strict mode;
- fails closed when an existing position cannot be safely priced;
- records the maximum factor and exposure in the signed risk authorization evidence.

The default ceiling is `2.5 ×` account capital per factor. This is a conservative software default, not an empirically optimized trading parameter. It must be evaluated from real Practice/replay evidence before any claim that it is economically optimal.

Configuration:

```text
FOREX_ENABLE_MACRO_FACTOR_RISK=true
FOREX_MACRO_FACTOR_POLICY_PATH=
FOREX_MAX_MACRO_FACTOR_EXPOSURE_FRACTION=2.5
FOREX_REQUIRE_MACRO_FACTOR_CLASSIFICATION=true
```

With no external policy path, the embedded taxonomy is equivalent to `config/macro-factor-clusters-v1.json`. A custom policy file can replace the taxonomy without modifying code.

Campaign policy identity now includes the complete macro-factor taxonomy, its exposure ceiling, strict-classification setting, and the previously omitted advanced drawdown/loss-streak/reserved-risk/gap-stress controls. Changing these values therefore changes the campaign fingerprint rather than silently mixing different risk behavior in one research cohort.

## v0.7.24 blinded technical human-ground-truth workflow

`src/forex_trader/research/technical_annotation.py` creates deterministic raw-candle annotation packets for validating zone, liquidity-sweep, structure-shift, retest, and direction semantics against independent humans.

Reviewer-visible packets contain only:

- instrument and timeframe;
- completed OHLCV candles;
- window start/end timestamps;
- immutable candle and packet hashes.

They deliberately exclude model zones, scores, detected sweeps, candidate direction, stops, targets, trade decisions, P/L, and future outcomes. The CLI also rejects unexpected input fields so outcome/model metadata cannot be casually included in a reviewer packet.

Ground-truth finalization requires at least two independent reviewer identities per packet. Unanimous labels finalize directly. Reviewer disagreement requires a third independent adjudicator; an adjudicator cannot be one of the packet reviewers.

A frozen batch is split chronologically using a fixed, non-tunable rule: the first `floor(2N/3)` packets are calibration and the final one-third are holdout. The manifest cryptographically binds the batch identity, frozen cutoff, and exact packet IDs in each partition.

Operator tools:

```bash
python scripts/create_technical_annotation_batch.py raw-chart-windows.json \
  --as-of 2026-08-07T20:00:00Z \
  --batch-output technical-annotation-batch.json \
  --manifest-output technical-holdout-manifest.json

python scripts/finalize_technical_annotations.py \
  technical-annotation-batch.json \
  technical-holdout-manifest.json \
  reviewer-submissions.jsonl \
  --adjudications adjudications.jsonl \
  --partition calibration \
  --output calibration-ground-truth.jsonl
```

The software workflow is now implemented. The audit requirement for **actual independent human ground truth is not complete until real expert labels are collected**. Code tests cannot substitute for that evidence.

## v0.7.24 research-only flow strategies

`src/forex_trader/research/flow_strategies.py` implements explicit research state machines for the two previously registry-only audit families.

`FlowDivergenceResearchPolicy` requires a non-local centralized flow source, minimum source confidence, normalized directional pressure, an opposing price move, a key location, and finally a structure shift to reach `CONFIRMED`.

`VwapRepositioningResearchPolicy` requires a non-local centralized source, actual centralized VWAP, a decisive cross/repositioning beyond a pip-distance threshold, aligned normalized flow pressure, and structure shift to reach `CONFIRMED`.

Both policies expose states `INELIGIBLE`, `WATCHING`, `ARMED`, and `CONFIRMED`. Neither produces a `TradeCandidate`, risk authorization, or broker order. `ResearchFlowSignal.executable` is always false.

This closes the missing software state-machine portion of the audit. It does **not** close the data/evidence gate: CME/equivalent centralized data, contract mapping, feature validation, historical replay, prospective shadow evidence, and promotion analysis remain external requirements.

## v0.7.23 external-data runtime retained

The vendor-neutral point-in-time adapters from v0.7.23 remain in place for economic consensus/actuals/schedules, news receipt time, cross-asset repricing, and centralized flow. External context is captured at the decision timestamp with source/health/error lineage. Scheduled calendar events enter the existing hard event blackout. Future schedule/news/flow observations are excluded.

A configured vendor adapter is not equivalent to an acquired licensed feed. The repository still does not bundle commercial economic-calendar/news feeds, rates/futures data, or CME/equivalent centralized flow.

## Research/evidence integrity

The following boundaries remain mandatory:

- candidate quality is not a calibrated probability;
- future observations are excluded from point-in-time decisions;
- decision evidence and later outcome labels remain separate;
- campaign fingerprints change when outcome-affecting risk policy changes;
- chronological calibration/holdout or train/validation/test separation is preserved;
- human validation cannot be replaced by model self-labeling;
- after-cost expectancy, drawdown, calibration, ablation, replay reproducibility, and sustained Practice evidence determine promotion.

The central-bank semantic workflow remains methodologically implemented but still requires independent human calibration labels, frozen acceptance criteria, and one sealed holdout evaluation. No semantic-validity claim is inferred from CI.

## Still external/evidence-gated after v0.7.24

- licensed multi-country economic-calendar and true point-in-time consensus acquisition;
- licensed real-time news acquisition and prospective event-classification evidence;
- rates/rate-futures/equity/volatility/commodity/USD/carry cross-asset acquisition;
- CME/equivalent centralized FX futures flow plus contract-roll/orientation mapping;
- real expert technical labels for the new blinded chart corpus;
- independent central-bank calibration labels and one-time sealed holdout evaluation;
- historical executable bid/ask/tick plus PIT macro/news/cross-asset/flow archives;
- empirical calibration of macro-factor taxonomy and exposure limits;
- sustained multi-session authenticated OANDA Practice evidence and mature outcomes;
- evidence-backed promotion of shadow/research strategies or position-management policies;
- full production observability, provider/strategy/execution/risk dashboards, alerting, durable event backbone, and scaled deployment controls.

## Validation boundary

The standard CI still runs compilation, dependency integrity, secret scanning, critical Ruff, strict typing, full pytest with branch-aware coverage, and an offline protected paper-order smoke on Python 3.11 and 3.13. v0.7.24 adds a dedicated audit-gate workflow that separately lints, strictly type-checks, and tests the new macro-factor, technical-annotation, campaign-identity, and research-flow surfaces.

Passing software CI proves invariants and implementation integrity. It does not prove a profitable edge, a live licensed-data connection, or authenticated broker success.

## OANDA Practice sequence

Because the current development date is a closed-market weekend, representative broker execution evidence remains deferred rather than manufactured from stale conditions. When markets and deployment network access permit, the evidence sequence remains:

```text
authenticated read-only account/pricing/candle/metadata check
-> transaction/state reconciliation
-> all-pair shadow campaign
-> separately gated broker-minimum protected open/verify/close round trip
-> capped Practice campaign
-> mature outcome labeling / ablation / after-cost analysis
```

See `docs/50_V0_7_24_RISK_AND_TECHNICAL_VALIDATION.md` and `config/audit-traceability-v0.7.24.json` for the release-specific audit mapping.
