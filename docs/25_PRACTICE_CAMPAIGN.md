# 25 — Evidence-First OANDA Practice Campaign

## Purpose

The Practice campaign exists to collect broker/runtime evidence after software validation. It does **not** lower strategy thresholds to manufacture trades, and it is not a substitute for historical validation.

The campaign answers operational questions with data: which pairs were eligible, which setup/risk/context gates blocked entries, which broker states occurred, how execution behaved, and whether the promotion gate remains blocked.

## Safety model

`PracticeCampaignRunner` delegates every evaluation and order submission to `TradingEngine`. It cannot bypass point-in-time fundamentals, event/holiday blackouts, structural setup requirements, spread/send-time geometry checks, marked-loss limits, currency/margin/correlation risk, execution claims/account locks, size-aware fresh pricing, `priceBound`, dependent protection verification, reconciliation or persistent uncertainty halts.

A campaign adds a strict **new-order budget per cycle**. Once that budget is spent, remaining instruments continue with `execute=False`, preserving opportunity/rejection evidence without taking additional risk.

The campaign stops the current cycle by default on any unresolved broker state: `created`, `acknowledged`, `partially_filled`, `unknown`, `reconciliation_required`, `closing` or `emergency_close`. Cancelled and deterministically rejected orders are recorded separately.

## Fundamental eligibility preflight

When fundamentals are required, an execution campaign automatically removes pairs whose current point-in-time fundamental confidence cannot meet the configured `minimum_fundamental_confidence`. This is an efficiency optimization only: those pairs are guaranteed to fail the later fundamental gate, so fetching two candle histories and live pricing for them adds cost but cannot produce an order.

The preflight does **not** authorize a trade. Every selected pair still goes through the complete quote-time technical, fundamental, context, risk and execution pipeline.

Shadow campaigns intentionally scan the full universe by default so missing fundamental coverage remains visible as diagnostic evidence. To make a shadow campaign use only currently eligible pairs:

```bash
python scripts/run_practice_campaign.py \
  --all-currency-pairs \
  --eligible-only \
  --max-cycles 1
```

If no pairs pass required fundamental preflight, the execution campaign exits with an instruction to improve legitimate point-in-time data or run a shadow diagnostic. It does not recommend lowering confidence or risk gates.

## Policy cohorts

Every newly generated evidence row includes:

- `campaign_id` — one run-level identity shared by all cycles from that runner;
- `policy_fingerprint` — deterministic SHA-256-derived identity for the outcome-affecting configuration;
- `policy_context` — a secret-free JSON-safe description of that policy;
- `campaign_metadata` — universe source/counts and preflight diagnostics.

The policy context includes strategy thresholds/requirements, risk limits, timeframe policy, correlation configuration, OANDA/simulation engine/broker class, shadow/paper state, maximum slippage and adaptive cost-model configuration. The campaign script also fingerprints execution-vs-shadow mode, the per-cycle order budget and whether fundamental preflight is active.

Credentials, account IDs and API tokens are deliberately excluded.

The cost model is adaptive. Its **algorithm/configuration** belongs to the cohort; every observed spread/slippage sample does not create a new fingerprint. Realized execution observations remain evidence inside that cohort.

Changing a strategy/risk/timeframe/campaign policy produces a different fingerprint. Therefore campaign evidence from an experiment cannot be silently combined with evidence from another policy.

## Required sequence before execution

1. Configure OANDA Practice credentials outside Git/chat.
2. Run the read-only probe:

   ```bash
   python scripts/smoke_oanda.py
   ```

3. Synchronize broker state:

   ```bash
   forex-trader sync
   ```

4. Run one all-pair shadow cycle:

   ```bash
   python scripts/run_practice_campaign.py \
     --all-currency-pairs \
     --max-cycles 1
   ```

5. Review `campaign-evidence.jsonl`, decisions, cost samples and `forex-trader promotion`.
6. Analyze that policy cohort.
7. Separately verify the broker-minimum protected open/verify/close round trip.
8. Only then enable OANDA Practice writes.
9. Begin with at most one new order per cycle.

```dotenv
FOREX_PROVIDER=oanda
FOREX_MODE=paper
FOREX_ENABLE_PAPER_ORDERS=true
OANDA_API_TOKEN=...
OANDA_ACCOUNT_ID=...
```

```bash
python scripts/run_practice_campaign.py \
  --execute \
  --all-currency-pairs \
  --max-orders-per-cycle 1 \
  --max-cycles 12
```

The default interval is one configured lower-timeframe bar. With `FOREX_LOWER_TIMEFRAME=M5`, 12 cycles represent roughly one hour of scan cadence.

## Evidence output

Each cycle records requested/evaluated instrument counts; candidates/abstentions; risk grants/denials; submitted/filled/protected/rejected/cancelled/unknown/reconciliation/emergency counts; generalized unresolved count; complete broker `order_statuses`; provider errors; rejection/risk histograms; promotion state; timestamps; policy cohort identity; and campaign metadata.

The analyzer remains backward compatible with older evidence. Rows without a fingerprint form the special `legacy` cohort; old `orders_unknown` evidence can conservatively infer unresolved state.

## Cohort-safe analysis

Analyze a file containing one policy cohort:

```bash
python scripts/analyze_campaign.py campaign-evidence.jsonl
```

If the file contains more than one fingerprint, analysis fails rather than averaging incompatible policies. Select a cohort explicitly:

```bash
python scripts/analyze_campaign.py campaign-evidence.jsonl \
  --policy-fingerprint 0123456789abcdef01234567
```

Within a selected fingerprint, contradictory `policy_context` values are rejected. The analyzer also rejects internally impossible trade/risk/order counts and inconsistent order-status histograms. Unknown/new abstention codes remain unclassified until their semantics are mapped and tested.

## Diagnosis precedence

Operational integrity outranks strategy optimization:

1. unresolved broker execution/protection state;
2. provider/authentication/data errors when material;
3. deterministic broker rejection/cancellation when material;
4. evidence sufficiency within the selected policy cohort;
5. unclassified rejection semantics;
6. fundamental-data bottlenecks;
7. market-context constraints;
8. strategy-formation constraints;
9. portfolio-risk constraints;
10. clean/selective operation.

Emergency-close evidence means dependent protection could not be verified and blocks further Practice-risk recommendations until broker protection behavior is resolved.

## Optimization rule

Do not respond to low trade frequency by blindly lowering `FOREX_MINIMUM_SCORE`, fundamental confidence, structural requirements or risk controls.

- No location/sweep: inspect declared-liquidity coverage and setup definition.
- No structure shift/retest: the setup did not complete; abstention is intended.
- Fundamental uncalibrated: improve legitimate point-in-time data coverage.
- Spread/late entry: treat as execution/context evidence.
- Correlation/margin/currency exposure: treat as portfolio evidence.
- Broker reject/cancel: inspect metadata, constraints and payloads.
- Any unresolved broker/protection state: stop new risk and reconcile.
- Unclassified rejection: define/test semantics before optimization.

A threshold, timeframe or management change should only be proposed when the hypothesis improves untouched historical validation and relevant after-cost Practice evidence. The resulting campaign must have a new policy fingerprint so before/after evidence remains separable.

## Current external blocker

This execution environment does not currently expose OANDA Practice credentials. Campaign/cohort/analyzer behavior can be software- and simulation-tested here, but a real authenticated Practice campaign cannot be honestly claimed until those credentials are configured externally.
