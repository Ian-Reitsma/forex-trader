# 34 — v0.7.8 Paired Outcome Maturity

v0.7.8 turns the prospective six-variant component stream introduced in v0.7.7 into conservative paired outcome evidence. It remains research-only and adds no Practice or live-money authority.

## Why the maturity layer exists

A component ablation is not useful evidence merely because six decisions were generated from one frozen snapshot. Every variant needs an outcome on the same future-price denominator. Tradeable variants may have different entry/stop/target geometry; nontradeable variants still represent a valid policy action and therefore must remain in the denominator as 0R.

The maturity layer is deliberately separate from capture so future outcomes are unavailable when variants are generated.

## Decision-time cost identity

New prospective rows persist the exact frozen quote bid/ask. Every variant within one snapshot must share the same quote context as well as snapshot payload hash, policy fingerprint, instrument and signal time.

The full frozen replay also verifies bid/ask equality with the actual production trace before the paired decision group is accepted.

A tradeable variant without captured quote context cannot be matured. The labeler fails closed instead of assuming zero spread.

## Conservative trade outcome semantics

`mature_ablation_outcomes()` delegates tradeable variants to the existing `evaluate_candidate_outcome()` engine used by ordinary decision evidence. That preserves one implementation for:

- captured decision-time spread;
- entry slippage;
- exit slippage;
- gap-through stop behavior;
- executable-side OHLC approximation;
- stop-first same-bar stop/target ambiguity;
- maximum-bar timeout exits;
- realized R, bars held, exit reason and estimated cost R.

A target/stop can mature before the full horizon. A timeout is not mature until all configured bars are available.

## Atomic snapshot writes

Maturity is atomic at the six-variant snapshot level.

If five variants are nontradeable and therefore already known to be 0R, but the sixth variant is still an open/pending future path, the labeler writes **zero** rows for that snapshot. Once the tradeable sibling becomes terminal or its full timeout horizon exists, all six rows are emitted together.

This prevents append-only output from containing partial paired groups that would later invalidate component expectancy calculations.

## Nontradeable and evaluator-error rows

A nontradeable policy action is recorded as:

```text
status=abstain
realized_r=0
bars_held=0
```

An evaluator failure is retained as:

```text
status=evaluation_error
realized_r=0
bars_held=0
```

The rejection/error reason is preserved as `exit_reason`. These are policy-level per-signal returns, not claims that a trade occurred.

## Matured provenance

Each `MaturedAblationOutcome` now retains:

- snapshot/payload/policy/variant identity;
- realized R and status;
- label timestamp;
- labeling policy string;
- bars held;
- exit reason;
- ambiguous-bar flag;
- estimated cost R.

The paired artifact SHA-256 includes this provenance so a change in maturity assumptions changes artifact identity even when nominal R happens to match.

## Read-only OANDA labeler

Run:

```bash
python scripts/label_ablation_decisions.py \
  ablation-decisions.jsonl \
  --output matured-ablation-outcomes.jsonl \
  --maximum-bars 24 \
  --entry-delay-bars 0 \
  --entry-slippage-pips 0.10 \
  --exit-slippage-pips 0.10
```

The script requires the OANDA provider configuration because real future-path labels use OANDA Practice historical candles. It constructs `SafeOandaPracticeClient` and calls historical `candles_between` only. It has no market-order, trade-close or account mutation path.

Existing output is validated before resume. Duplicate rows or incomplete six-variant matured groups fail rather than being silently skipped.

## Complete workflow

```text
shadow campaign
  -> ablation-decisions.jsonl
  -> wait for future path maturity
  -> label_ablation_decisions.py
  -> matured-ablation-outcomes.jsonl
  -> assemble_paired_ablations.py
  -> component full-vs-ablated expectancy
  -> research promotion bundle
```

`assemble_paired_ablations.py` still binds the component evidence to the primary research dataset ID and requires the same full-policy baseline/sample denominator expected by the promotion report.

## What this release proves

Deterministic CI can prove:

- quote cost context survives capture/serialization;
- six-variant prospective group integrity;
- atomic maturity behavior;
- 0R abstention/error denominator semantics;
- early terminal maturity versus complete timeout maturity;
- conservative same-bar ambiguity;
- captured spread changes modeled path outcomes;
- missing cost provenance fails closed;
- append/resume output requires complete groups;
- the labeler contains only read-only OANDA market-data access.

It cannot prove that any component adds positive expectancy. That requires a sufficiently large prospective dataset collected over real market conditions.

## Next evidence milestone

Accumulate the corpus. Do not modify production thresholds simply to accelerate sample count. Once enough paired snapshots mature, compute component incremental expectancy and uncertainty on chronological untouched evidence. Components with neutral or negative incremental value should become candidates for simplification; components with positive value still require calibration, robustness and provider-quality checks before any authority change.
