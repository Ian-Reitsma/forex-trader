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

## What v0.7.7 now captures

v0.7.7 wires each predefined component mask into the actual pre-risk production signal path and can capture all six variants automatically during a normal shadow campaign.

The ordinary all-on path remains the production default. Research masks can disable exactly one of:

- **fundamentals** — removes fundamental admissibility/conflict and fundamental independent-confirmation effects;
- **flow** — removes broker-tick flow scoring/source contribution and flow confirmation;
- **session** — removes session score/rollover suppression and session-derived regime effects;
- **zone quality** — removes the zone-quality eligibility/contribution while preserving the underlying price history;
- **retest** — removes retest entry eligibility and score contribution while preserving the original sweep/structure context.

The variants rerun `assess_technicals` plus `RegimeAwareSignalFusionPolicy`; they are not synthetic outputs from a research-only scoring function.

## Exact production-signal snapshot

`SignalEvaluationInputs` captures the inputs from one actual shadow decision:

- lower completed candles;
- higher completed candles;
- the exact quote returned in the actual decision trace;
- the point-in-time fundamental assessment at that quote timestamp;
- the adaptive spread ceiling used by signal fusion;
- scheduled-event blackout reasons;
- rollover blackout state.

`FxTradingEngine.evaluate_with_signal_inputs()` is restricted to `execute=False`. It holds an outer evaluation-local candle snapshot around the normal engine evaluation, then freezes the inputs before that scope closes. Re-requesting the lower/higher histories therefore reuses the completed candles already read by the production decision. The capture path does not request another executable quote.

Regression coverage compares a normal shadow campaign against a paired-capture campaign and requires the same underlying provider candle/quote call counts.

## Frozen snapshot identity

`FrozenAblationSnapshot` binds each research evaluation group to:

- snapshot ID;
- instrument;
- timezone-aware signal time;
- policy fingerprint;
- canonical immutable payload JSON;
- SHA-256 of that payload.

The frozen payload includes the production-signal inputs and context-hard-gate state above. `ProspectiveAblationCollector` rejects any evaluator that changes snapshot ID, payload hash, policy fingerprint, instrument or signal time. Variants cannot quietly fetch different candles, quotes or macro state and call the result an ablation.

Before paired rows are appended, the `full` frozen replay is compared with the actual production trace. Tradeability, setup family, direction, quality score, entry/stop/target geometry and rejection code must match exactly. A mismatch fails the capture rather than writing misleading paired evidence.

## Context hard gates

The production signal is not just technical assessment plus fusion. Scheduled-event blackout and rollover blackout occur afterward in the engine and therefore are frozen and replayed too.

Scheduled-event blackout remains active for every component variant because it is not one of the five declared ablations. Rollover suppression is part of the session component, so the `no_session` variant intentionally removes that session-derived hard gate while all other variants retain it.

## Shadow-only authority boundary

Automatic paired capture is enabled with:

```bash
python scripts/run_practice_campaign.py \
  --all-currency-pairs \
  --max-cycles 1 \
  --decision-evidence-path decision-evidence.jsonl \
  --ablation-evidence-path ablation-decisions.jsonl
```

`--ablation-evidence-path` cannot be combined with `--execute`. `ProductionAblationAdapter` and `ShadowAblationRuntime` also independently require SHADOW semantics with paper-order writes disabled. The evaluator contains no broker submission path.

A successful instrument capture appends exactly six `ProspectiveAblationDecision` rows. Research capture errors are counted separately from campaign provider/strategy/risk/execution errors so failed instrumentation cannot distort operational diagnostics.

## Paired denominator

Every declared variant produces one prospective row. Abstentions are rows. Evaluator exceptions are rows. A variant evaluation failure is represented explicitly rather than silently removing that variant from the evidence set.

After the future-price horizon matures, each snapshot must have one `MaturedAblationOutcome` for every required variant. Missing or duplicate variants fail the paired assembler. Component expectancy is therefore computed on the exact same snapshot denominator as the full policy.

For nontradeable variants, maturity logic must retain the row in the denominator rather than condition the analysis on variants that happened to trade. For tradeable variants, future-path labeling must use conservative point-in-time execution semantics consistent with the ordinary research outcome pipeline. This maturity/labeling step is the next implementation milestone after v0.7.7 capture.

## Dataset identities

Two identities are intentionally separate:

1. **Primary dataset ID** — SHA-256 identity from the setup-isolated decision/outcome research corpus used by the promotion report.
2. **Paired ablation artifact ID** — SHA-256 identity of the matured variant-outcome artifact itself.

Promotion-compatible ablation rows carry the primary dataset ID because they claim to measure components on that primary holdout. The output also records the paired artifact ID so the exact counterfactual evidence file remains independently identifiable.

The promotion bundle additionally checks that each ablation has the same untouched-test sample count and same full-policy baseline expectancy as the primary report. Supplying the correct primary dataset ID is therefore necessary but not sufficient to make mismatched evidence pass.

## Offline assembly after maturity

Once prospective variant outcomes have matured:

```bash
python scripts/assemble_paired_ablations.py \
  matured-ablation-outcomes.jsonl \
  --primary-dataset-id <dataset_id_from_research_report> \
  --output ablation-evidence.json
```

The command has no broker client, credential path or execution authority.

## What v0.7.7 does not claim

v0.7.7 proves production-seam wiring, same-snapshot capture, full-policy replay parity, context-gate replay, and the shadow-only authority boundary in deterministic tests. It does **not** claim that any component improves profitability.

That requires a sufficiently large prospective corpus whose future outcomes have matured. Only paired after-cost outcome evidence can tell us whether fundamentals, flow, session, zone quality or retest add positive incremental expectancy, are neutral, or reduce expectancy. Low sample count is not a reason to loosen production thresholds or to infer component value from retrospective feature importance.

## Promotion boundary

Even complete, favorable paired ablations satisfy only one research-promotion requirement. Calibration, untouched holdout economics, drawdown, provider integrity, deterministic replay and optional Phase-D evidence remain independent gates. A passing bundle can nominate a `shadow_candidate`; it cannot grant Practice authority.
