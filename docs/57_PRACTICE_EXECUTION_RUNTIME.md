# v0.7.38 Practice Execution Runtime and Geometry

## What the frontend does

`forex-trader serve` runs the FastAPI control plane and packaged cockpit. It does **not** run strategy evaluation cycles and it does not place OANDA Practice orders by itself. A healthy/streaming frontend therefore proves API and broker-read connectivity, not that the strategy runner is active.

The Practice execution process is separate and explicit:

```bash
python scripts/run_practice_campaign.py \
  --execute \
  --all-currency-pairs \
  --max-orders-per-cycle 1 \
  --max-cycles 12 \
  --decision-evidence-path campaign-decisions.jsonl
```

With the default M5 lower timeframe this is a bounded roughly one-hour campaign. Re-run the campaign for additional Practice evidence after inspecting the completed cycle report. The runner refreshes the free official fundamental state before building its engine, pre-filters pairs that cannot satisfy fundamental coverage, caps new orders per cycle, and stops on unresolved broker state.

The frontend can remain running in a second terminal:

```bash
forex-trader serve --host 127.0.0.1 --port 8000
```

Both processes use the same configured SQLite evidence ledger, so the cockpit can display the decisions, broker account state and positions produced by the Practice runner.

## Diagnostic finding that motivated v0.7.38

The Aug. 10 Practice diagnostic showed a healthy broker/control path but no active strategy orders: all 75 persisted decisions were abstentions. The dominant recorded rejection was `NO_STRUCTURAL_TARGET`, but the fusion policy checked geometry before structure shift, entry confirmation, fundamental conflict and score. That ordering allowed immature/low-score setups to be mislabeled as target failures.

v0.7.38 moves the missing-geometry rejection after the causal setup, macro and quality gates. This is primarily an observability correction: it does not authorize a trade that failed an earlier gate.

## Confirmed post-shift stop geometry

The sweep/reclaim detector previously left the stop behind the original sweep extreme (or farther zone distal) even after the market had shifted structure and confirmed a retest. That can make an otherwise mature setup's risk distance stale relative to the later entry geometry.

v0.7.38 may tighten that baseline stop to the latest **confirmed post-shift pivot** when all of the following are true:

1. declared liquidity was swept/reclaimed;
2. a post-sweep structure shift was confirmed;
3. the entry retest/continuation was confirmed;
4. a higher-low (long) or lower-high (short) formed *after* the shift;
5. the pivot has the normal right-hand confirmation bars, so no future/unconfirmed pivot is used;
6. the new stop is strictly inside the baseline invalidation and still on the protective side of entry.

The original stop remains in force when no such pivot exists. The optimization can tighten risk but can never widen it.

All downstream controls remain unchanged: minimum structural reward/risk 1.35, configured score threshold, spread cap, slippage cap, independent confirmations, fundamental confidence/conflict, portfolio risk, reconciliation, send-time geometry revalidation, position limits, drawdown limits and the Practice-only broker boundary.

## Profitability status

This change is intended to improve executable geometry and candidate quality/frequency; it is not a guarantee of profit. The repository's prior sealed validation did not establish a stable positive edge, so profitability must be demonstrated prospectively with new Practice trades and untouched validation data rather than asserted from development results.
