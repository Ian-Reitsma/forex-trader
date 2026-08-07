# 27 — Research Evidence, Calibration, and Expected Value

This workflow converts shadow/Practice decisions into point-in-time research evidence without granting execution authority. It is designed to answer whether a strategy cohort has repeatable after-cost expectancy, not whether a short session happened to make money.

## Evidence layers

Cycle-level campaign evidence remains the operational diagnosis surface: instruments evaluated, abstentions, rejection codes, risk denials, broker states, unresolved writes, and provider failures.

Decision-level evidence is separate. When `--decision-evidence-path` is supplied, the campaign writes one JSONL row for every instrument attempt. Each row records the immutable campaign and policy identity, signal time, setup family/state, regime, session, confirmation categories and source identities, candidate score/components, executable entry/stop/target geometry, captured quote, risk result, order state, and raw candidate evidence. Evaluation errors are recorded as failed attempts rather than disappearing from the dataset.

The decision stream is intentionally not an outcome stream. No result is attached until enough later market data exists.

## Capture shadow decisions

For an authenticated OANDA read-only/shadow campaign:

```bash
python scripts/run_practice_campaign.py \
  --all-currency-pairs \
  --max-cycles 1 \
  --evidence-path campaign-evidence.jsonl \
  --decision-evidence-path decision-evidence.jsonl
```

The permanent `OANDA Practice Validation` workflow writes detailed shadow and Practice decision streams into its existing evidence artifact automatically.

## Label matured outcomes

After decisions have aged enough to observe their configured outcome horizon, label them from later OANDA Practice-market candles:

```bash
python scripts/label_decision_evidence.py \
  decision-evidence.jsonl \
  --output outcome-evidence.jsonl \
  --maximum-bars 24 \
  --entry-slippage-pips 0.10 \
  --exit-slippage-pips 0.10
```

The labeler is read-only. It uses the OANDA historical candle endpoint and never submits, changes, or closes an order.

Outcome labeling uses the existing conservative OHLC semantics. If stop and target are both reachable within one candle, the stop is assumed first. Captured decision-time bid/ask spread is included by default, and explicit entry/exit slippage stress may be added.

A terminal target or stop can be labeled as soon as it occurs. A time-exit/timeout is not labeled until the complete observation horizon is available. This prevents an unfinished live path from entering historical training data as a false timeout.

Each outcome row is keyed back to the originating decision and retains campaign ID, policy fingerprint, signal time, label policy, realized R, holding bars, fill assumptions, ambiguity flag, MAE/MFE, and estimated execution cost.

## Three-outcome probability semantics

The empirical model estimates three mutually exclusive path outcomes:

- target before stop;
- stop before target;
- neither barrier before the observation horizon, resulting in a time exit.

A profitable time exit is not counted as a target hit. A losing time exit is not counted as a stop hit. Their empirical R distribution enters expected value through the separate timeout probability and expected timeout R.

With no observations, the model remains neutral at 50% target / 50% stop / 0% timeout rather than inventing a timeout frequency. Once observations exist, target, stop, and timeout rates are regularized independently.

## Cohort hierarchy

The default hierarchy is:

```text
setup + regime + session
        ↓ sparse fallback
setup + regime
        ↓
setup
        ↓
all eligible history
```

Instrument is added only when explicitly requested and sample size supports it. This prevents a handful of pair-specific wins from being treated as a stable edge.

## Chronological analysis

Run the analyzer only after there is a meaningful labeled sample:

```bash
python scripts/analyze_research_dataset.py \
  decision-evidence.jsonl \
  outcome-evidence.jsonl \
  --minimum-labeled-trades 200 \
  --minimum-cohort-trades 30 \
  --minimum-ev-sample 50
```

The analyzer rejects datasets that mix policy fingerprints. One immutable strategy/software/policy cohort must be analyzed at a time.

The dataset is split chronologically into train, validation, and untouched test folds. The train fold estimates cohort outcomes. Validation measures target-probability Brier score and expected calibration error. Training and validation history are then available when the untouched test fold is evaluated. Test outcomes are never used to fit their own probability estimate or calibration threshold.

## Research expected-value gate

For each untouched test decision, the research-only EV gate combines:

```text
P(target) × structural reward R
- P(stop) × stop-loss R
+ P(timeout) × empirical timeout R
- captured spread cost
- historical execution/slippage cost
- adverse-selection allowance
- operational-uncertainty allowance
```

A candidate is not research-eligible unless all configured evidence conditions pass: minimum cohort sample, acceptable probability confidence width, acceptable validation calibration error, positive ordinary after-cost EV, and positive conservative lower-bound EV.

The conservative calculation lowers target probability, raises stop probability, and uses the adverse side of timeout uncertainty. A high point estimate with a wide interval therefore remains rejected.

This EV decision has no broker authority. It cannot replace risk authorization, reconciliation readiness, protection requirements, policy authority, or the separate Practice promotion gate.

## Interpretation

A useful comparison is the untouched-test performance of all candidates versus only EV-eligible candidates. Improvement must be evaluated on expectancy, total R, drawdown, sample size, and calibration together. A smaller subset with one lucky winner is not evidence of an edge.

The next required research layer is controlled ablation on the same immutable decision/outcome dataset: full policy versus no-fundamentals, no-flow, no-session, no-zone-quality, no-retest, and Phase-D entry/management variants. Components should be promoted only when their incremental value survives chronological holdout and realistic cost assumptions.

## Practice boundary

Nothing in this workflow enables live-money trading. OANDA remains locked to fxTrade Practice. Strategy authority remains defined by `config/system-policy-v0.7.json`; detailed research evidence and a positive EV report are necessary evidence for later review, not an automatic promotion mechanism.
