# 25 — Evidence-First OANDA Practice Campaign

## Purpose

The Practice campaign exists to collect broker/runtime evidence after software validation. It does **not** lower strategy thresholds to manufacture trades, and it is not a substitute for historical validation.

The campaign is designed to answer operational questions with data:

- How many broker currency instruments were evaluated?
- How often did the structure/location strategy produce a trade candidate?
- Which rejection codes dominate abstentions?
- Which independent risk rules deny otherwise valid candidates?
- How often are orders submitted, protected, rejected, or left in an unknown state?
- Does observed slippage/spread remain inside configured limits?
- Does the persistent promotion gate remain blocked, and why?

## Safety model

`PracticeCampaignRunner` delegates every evaluation and order submission to `TradingEngine`. It does not bypass:

- point-in-time fundamentals;
- event/holiday blackouts;
- structural entry requirements;
- spread and send-time geometry checks;
- daily marked-loss limits;
- currency/margin/correlation portfolio risk;
- execution claims and account locks;
- size-aware fresh pricing;
- `priceBound`;
- protection verification;
- persistent execution-uncertainty halts.

A campaign also adds an operator-level **new-order budget per cycle**. Once that budget is spent, remaining instruments continue to be evaluated with `execute=False`. This preserves opportunity and rejection evidence without increasing risk.

If a submitted order is recorded as `UNKNOWN`, the campaign stops the current cycle immediately. The engine's reconciliation/halt logic remains authoritative.

## Required sequence before execution

Do not begin with an all-pair write campaign. Use this order:

1. Configure OANDA Practice credentials outside Git/chat.
2. Run the read-only probe:

   ```bash
   python scripts/smoke_oanda.py
   ```

3. Synchronize broker state:

   ```bash
   forex-trader sync
   ```

4. Run a one-cycle all-pair **shadow** campaign:

   ```bash
   python scripts/run_practice_campaign.py \
     --all-currency-pairs \
     --max-cycles 1
   ```

5. Review `campaign-evidence.jsonl`, recent decisions, cost samples, and `forex-trader promotion`.
6. Separately verify the broker-minimum protected open/verify/close plumbing test.
7. Only then enable OANDA Practice writes in `.env`:

   ```dotenv
   FOREX_PROVIDER=oanda
   FOREX_MODE=paper
   FOREX_ENABLE_PAPER_ORDERS=true
   OANDA_API_TOKEN=...
   OANDA_ACCOUNT_ID=...
   ```

8. Start with one new order maximum per cycle:

   ```bash
   python scripts/run_practice_campaign.py \
     --execute \
     --all-currency-pairs \
     --max-orders-per-cycle 1 \
     --max-cycles 12
   ```

The default interval is one configured lower-timeframe bar. With `FOREX_LOWER_TIMEFRAME=M5`, 12 cycles therefore represent roughly one hour of scan cadence.

## Evidence output

Each cycle appends one JSON object to the configured JSONL evidence path. Fields include:

- requested/evaluated instrument counts;
- trade candidates and abstentions;
- risk grants and denials;
- submitted/filled/protected/rejected/unknown order counts;
- error counts and exception classes;
- rejection-code histogram;
- primary risk-denial reason histogram;
- promotion-ready snapshot;
- start/finish timestamps.

Analyze accumulated evidence with:

```bash
python scripts/analyze_campaign.py campaign-evidence.jsonl
```

The analyzer fails closed on internally inconsistent evidence and treats unknown/new abstention codes as unclassified until their semantics are explicitly mapped and tested.

## How optimization should use campaign evidence

Do not react to low trade frequency by simply lowering `FOREX_MINIMUM_SCORE` or removing structure/liquidity gates.

Optimization should first classify the bottleneck:

- **No location/sweep**: inspect whether the declared liquidity map is missing a legitimate pool or the universe/session is inappropriate.
- **No structure shift/retest**: the market did not complete the setup; abstention is the intended behavior.
- **Fundamental uncalibrated**: improve the point-in-time data feed rather than disabling fundamentals blindly.
- **Spread/late entry**: execution conditions are poor; do not compensate by increasing target or risk.
- **Correlation/margin/currency exposure**: the candidate may be good in isolation but bad for the portfolio.
- **Broker reject**: inspect broker metadata/order constraints and request payloads.
- **Unknown order**: reconcile broker state before any new risk.

A threshold or management change should only be proposed after the same hypothesis improves untouched historical validation **and** relevant Practice evidence after costs.

## Current external blocker

This execution environment does not currently expose OANDA Practice credentials. The campaign and analyzer can therefore be fully software-tested and simulation-tested here, but a real authenticated Practice campaign cannot be honestly claimed until those credentials are configured externally.
