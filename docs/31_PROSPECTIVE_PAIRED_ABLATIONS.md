# 31 — Prospective Paired Ablations

The research-promotion bundle requires explicit evidence for:

```text
full
no_fundamentals
no_flow
no_session
no_zone_quality
no_retest
```

These cannot be inferred from feature importance and cannot be manufactured by deleting labels after a trade outcome is known. The objective is prospective counterfactual evaluation: freeze one point-in-time production signal snapshot, run every predefined variant against that same snapshot before future outcomes are known, retain every variant in the denominator, then compare matured outcomes on the same chronological holdout.

## Production-faithful capture

v0.7.7 wires each predefined component mask into the actual pre-risk production signal path and captures all six variants automatically during a normal shadow campaign.

The ordinary all-on path remains the production default. Research masks can disable exactly one of:

- **fundamentals** — fundamental admissibility/conflict and fundamental independent-confirmation effects;
- **flow** — broker-tick flow scoring/source contribution and flow confirmation;
- **session** — session score/rollover suppression and session-derived regime effects;
- **zone quality** — zone-quality eligibility/contribution while preserving the underlying price history;
- **retest** — retest entry eligibility and score contribution while preserving the original sweep/structure context.

The variants rerun `assess_technicals` plus `RegimeAwareSignalFusionPolicy`; they are not synthetic research-only scores.

## Exact production-signal snapshot

`SignalEvaluationInputs` captures the inputs from one actual shadow decision:

- lower completed candles;
- higher completed candles;
- the exact quote returned in the actual decision trace;
- the point-in-time fundamental assessment at that quote timestamp;
- the adaptive spread ceiling used by signal fusion;
- scheduled-event blackout reasons;
- rollover blackout state.

`FxTradingEngine.evaluate_with_signal_inputs()` is restricted to `execute=False`. It holds an outer evaluation-local candle snapshot around the normal engine evaluation, then freezes the inputs before that scope closes. Re-requesting lower/higher histories therefore reuses completed candles already read by the production decision. The capture path does not request another executable quote.

New v0.7.8 prospective rows also persist exact decision-time `quote_bid` and `quote_ask`. All six rows in one snapshot must share that quote identity, and the `full` frozen replay must match the actual production trace on bid/ask as well as tradeability, setup, direction, score, geometry and rejection code.

## Frozen snapshot identity

`FrozenAblationSnapshot` binds each research evaluation group to snapshot ID, instrument, timezone-aware signal time, policy fingerprint, canonical immutable payload JSON and payload SHA-256.

`ProspectiveAblationCollector` rejects any evaluator that changes snapshot ID, payload hash, policy fingerprint, instrument or signal time. JSONL loading additionally rejects duplicate variants, inconsistent quote context and incomplete six-variant groups.

## Context hard gates

Scheduled-event blackout and rollover blackout occur after technical/fusion evaluation in the production engine and are frozen/replayed too.

Scheduled-event blackout remains active for every component variant because it is not one of the five declared ablations. Rollover suppression is part of the session component, so `no_session` intentionally removes that session-derived hard gate while all other variants retain it.

## Shadow-only authority boundary

Automatic paired capture is enabled with:

```bash
python scripts/run_practice_campaign.py \
  --all-currency-pairs \
  --max-cycles 1 \
  --decision-evidence-path decision-evidence.jsonl \
  --ablation-evidence-path ablation-decisions.jsonl
```

`--ablation-evidence-path` cannot be combined with `--execute`. `ProductionAblationAdapter` and `ShadowAblationRuntime` independently require shadow semantics with paper-order writes disabled. The evaluator contains no broker submission path.

## Paired maturity in v0.7.8

v0.7.8 implements the future-path maturity step:

```bash
python scripts/label_ablation_decisions.py \
  ablation-decisions.jsonl \
  --output matured-ablation-outcomes.jsonl \
  --maximum-bars 24 \
  --entry-slippage-pips 0.10 \
  --exit-slippage-pips 0.10
```

Tradeable variants are labeled with the same `evaluate_candidate_outcome()` engine used by ordinary decision evidence. Captured spread, entry/exit slippage, gap-through stops, conservative stop-first same-bar ambiguity, terminal targets/stops and timeout R therefore share one implementation.

Nontradeable variants and evaluator failures remain in the denominator at 0R. This is policy-level per-signal return, not a claim that a trade occurred.

A tradeable row without captured quote context fails closed instead of assuming zero spread.

### Atomic group rule

No snapshot is partially appended. A target or stop may mature before the configured horizon, but a timeout requires the complete `maximum_bars` future path. If any tradeable sibling remains immature, all six outcomes for that snapshot remain pending. Once every tradeable sibling is terminal or timeout-mature, all six rows are written together.

Existing matured output is also validated as complete six-variant groups before resume.

## Matured provenance

`MaturedAblationOutcome` retains:

- snapshot payload/policy/variant identity;
- realized R and status;
- labeling timestamp and policy;
- bars held and exit reason;
- same-bar ambiguity flag;
- estimated cost R.

The paired artifact ID hashes that maturity provenance in addition to nominal R/status so changed assumptions change evidence identity.

## Dataset identities

Two identities remain intentionally separate:

1. **Primary dataset ID** — SHA-256 identity from the setup-isolated decision/outcome research corpus used by the promotion report.
2. **Paired ablation artifact ID** — SHA-256 identity of the matured variant-outcome artifact itself.

Promotion-compatible ablation rows carry the primary dataset ID because they claim to measure components on that primary holdout. The output separately records the paired artifact ID so the exact counterfactual evidence file remains independently identifiable.

The promotion bundle additionally checks that each ablation has the same untouched-test sample count and full-policy baseline expectancy as the primary report. Supplying the correct primary dataset ID is necessary but not sufficient to make mismatched evidence pass.

## Offline assembly after maturity

```bash
python scripts/assemble_paired_ablations.py \
  matured-ablation-outcomes.jsonl \
  --primary-dataset-id <dataset_id_from_research_report> \
  --output ablation-evidence.json
```

The assembler has no broker client, credential path or execution authority.

## What this lifecycle does not claim

Production-faithful capture plus conservative maturity does **not** prove that any component improves profitability. That requires a sufficiently large prospective corpus across real market conditions.

Only paired after-cost outcome evidence can tell us whether fundamentals, flow, session, zone quality or retest add positive incremental expectancy, are neutral, or reduce expectancy. Low sample count is not a reason to loosen production thresholds or infer component value retrospectively.

## Promotion boundary

Even complete, favorable paired ablations satisfy only one research-promotion requirement. Calibration, untouched holdout economics, drawdown, provider integrity, deterministic replay and optional Phase-D evidence remain independent gates. A passing bundle can nominate a `shadow_candidate`; it cannot grant Practice authority.
