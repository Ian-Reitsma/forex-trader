# 33 — v0.7.7 Automatic Paired Component Capture

v0.7.7 closes the gap between the prospective-ablation research contract and the real production signal path. It does not change Practice trading authority.

## Production seams

The ordinary decision path remains all components enabled. A research-only `DecisionComponentPolicy` can disable exactly one predefined component at a time: fundamentals, flow, session, zone quality or retest. The actual technical and regime-aware fusion functions consume that policy, so each counterfactual removes the component's real gates, score contribution and independent-confirmation effects.

## Same-snapshot capture

A shadow campaign can request an additional paired-ablation JSONL stream with `--ablation-evidence-path`. For each successfully captured instrument attempt, the engine first performs the normal production decision. While the same evaluation-local candle snapshot remains open, it freezes the completed lower/higher candles already read by that decision, the actual trace quote, point-in-time fundamentals, the adaptive spread ceiling, scheduled-event blackout reasons and rollover state.

The capture path does not request a second executable quote. Regression coverage compares provider call counts between an ordinary shadow evaluation and paired capture and requires them to be identical.

## Full-policy parity

Before any paired rows are appended, the frozen `full` replay must match the actual production candidate on:

- tradeable/abstain disposition;
- setup family;
- direction;
- quality score;
- entry price;
- stop loss;
- take profit;
- rejection code.

A mismatch is an ablation-capture failure, not valid research evidence.

## Context gates

Scheduled-event and rollover hard gates occur after technical/fusion evaluation in the production engine, so they are frozen and replayed too. Event blackout applies to every variant. Rollover is a session-derived effect and is therefore removed only by `no_session`.

## Authority boundary

Paired capture is rejected when campaign execution is enabled. The evaluator has no broker submission path, and the existing production-ablation runtime independently enforces shadow semantics with paper writes disabled. Capture failures are reported separately from provider, strategy, risk and broker errors.

## Evidence lifecycle

v0.7.7 produces prospective decision rows, not profitability claims. The next step is to mature every snapshot/variant against the same future-price horizon. Tradeable variants require conservative path labeling; abstentions and evaluator failures must remain in the denominator. Only after that paired maturity step can `paired_ablation_evidence` estimate each component's incremental expectancy against the full policy.

No strategy threshold, risk limit, setup authority or OANDA execution setting should be changed solely because the captured sample is small.
