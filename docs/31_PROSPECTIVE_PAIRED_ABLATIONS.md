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

These cannot be inferred from feature importance and cannot be manufactured by deleting labels after a trade outcome is known. The objective is prospective counterfactual evaluation: freeze one point-in-time production signal snapshot, run every predefined variant against that same snapshot before future outcomes are known, retain every variant in the denominator, mature all variants on the same future path, and quantify the paired component delta with uncertainty.

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

`SignalEvaluationInputs` captures the inputs from one actual shadow decision: lower/higher completed candles, the actual trace quote, point-in-time fundamentals, adaptive spread ceiling, scheduled-event blackout reasons, and rollover state.

`FxTradingEngine.evaluate_with_signal_inputs()` is restricted to `execute=False`. It holds an outer evaluation-local candle snapshot around the normal engine evaluation, then freezes the inputs before that scope closes. Re-requesting lower/higher histories therefore reuses completed candles already read by the production decision. The capture path does not request another executable quote.

v0.7.8 prospective rows persist exact decision-time `quote_bid` and `quote_ask`. All six rows in one snapshot must share that quote identity, and the `full` frozen replay must match the actual production trace on bid/ask as well as tradeability, setup, direction, score, geometry and rejection code.

## Frozen snapshot identity

`FrozenAblationSnapshot` binds each research evaluation group to snapshot ID, instrument, timezone-aware signal time, policy fingerprint, canonical immutable payload JSON and payload SHA-256.

`ProspectiveAblationCollector` rejects any evaluator that changes snapshot ID, payload hash, policy fingerprint, instrument or signal time. JSONL loading additionally rejects duplicate variants, inconsistent quote context and incomplete six-variant groups.

## Context hard gates

Scheduled-event blackout and rollover blackout occur after technical/fusion evaluation in the production engine and are frozen/replayed too. Event blackout remains active for every component variant. Rollover suppression is part of the session component, so `no_session` intentionally removes that session-derived hard gate while all other variants retain it.

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

```bash
python scripts/label_ablation_decisions.py \
  ablation-decisions.jsonl \
  --output matured-ablation-outcomes.jsonl \
  --maximum-bars 24 \
  --entry-slippage-pips 0.10 \
  --exit-slippage-pips 0.10
```

Tradeable variants are labeled with the same `evaluate_candidate_outcome()` engine used by ordinary decision evidence. Captured spread, entry/exit slippage, gap-through stops, conservative stop-first same-bar ambiguity, terminal targets/stops and timeout R therefore share one implementation.

Nontradeable variants and evaluator failures remain in the denominator at 0R. A tradeable row without captured quote context fails closed instead of assuming zero spread.

### Atomic group rule

No snapshot is partially appended. A target or stop may mature before the configured horizon, but a timeout requires the complete `maximum_bars` future path. If any tradeable sibling remains immature, all six outcomes remain pending. Once every tradeable sibling is terminal or timeout-mature, all six rows are written together.

## Paired uncertainty in v0.7.9

The component statistic is evaluated per frozen snapshot:

```text
component_increment_r = full_realized_r - ablated_realized_r
```

The assembler reuses the repository's deterministic paired-bootstrap mean interval from Phase-D research. Defaults are 90% confidence, 2,000 bootstrap iterations and seed `20260807`.

```bash
python scripts/assemble_paired_ablations.py \
  matured-ablation-outcomes.jsonl \
  --primary-dataset-id <dataset_id_from_research_report> \
  --output ablation-evidence.json \
  --confidence 0.90 \
  --bootstrap-iterations 2000 \
  --bootstrap-seed 20260807
```

Each component row records full and ablated expectancy, paired lower/upper confidence bounds, paired win/loss/tie counts, sample size, primary dataset ID, confidence, iteration count and seed.

### Promotion interpretation

The material-harm tolerance remains `0.05R`, now applied to the confidence interval of `full - ablated`:

```text
upper confidence bound < -0.05R
    -> rejected: component is confidently materially harmful

lower bound < -0.05R <= upper bound
    -> insufficient evidence: material harm cannot yet be ruled out

lower bound >= -0.05R
    -> component non-harm check passes; all other promotion gates still apply
```

Legacy mean-only artifacts remain parseable but are insufficient evidence because they lack uncertainty provenance. Promotion requires at least 90% confidence and 1,000 bootstrap iterations by default.

## Matured and dataset provenance

`MaturedAblationOutcome` retains snapshot/payload/policy/variant identity, realized R/status, labeling timestamp/policy, bars held, exit reason, same-bar ambiguity and estimated cost R. The paired artifact ID hashes that maturity provenance in addition to nominal R/status.

Two identities remain intentionally separate:

1. **Primary dataset ID** — SHA-256 identity from the setup-isolated decision/outcome research corpus used by the promotion report.
2. **Paired ablation artifact ID** — SHA-256 identity of the matured variant-outcome artifact itself.

Promotion does not trust the dataset ID string alone. Each required component must also match the primary untouched-test sample count and full-policy expectancy. A mismatch is a hard integrity rejection.

## What this lifecycle does not claim

Production-faithful capture, conservative maturity and paired uncertainty do **not** prove that any component improves profitability. That requires a sufficiently large prospective corpus across real market conditions.

Only paired after-cost outcome evidence can tell us whether fundamentals, flow, session, zone quality or retest add positive incremental expectancy, are neutral, or reduce expectancy. Low sample count is not a reason to loosen production thresholds or infer component value retrospectively.

## Promotion boundary

Even complete, favorable paired ablations satisfy only one research-promotion requirement. Calibration, untouched holdout economics, drawdown, provider integrity, deterministic replay and optional Phase-D evidence remain independent gates. A passing bundle can nominate a `shadow_candidate`; it cannot grant Practice authority.
