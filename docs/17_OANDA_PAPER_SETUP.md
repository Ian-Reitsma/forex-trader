# 17 — OANDA Practice Setup

OANDA fxTrade Practice is the initial external paper-trading platform. The adapter is locked to the practice REST host and cannot be pointed at OANDA's live-money REST host through configuration.

## Credential handling

1. Create an OANDA demo account for the applicable regulatory division.
2. In the OANDA account portal, open **Manage API Access** and generate a personal access token.
3. Store the token only in a local `.env` file, an operating-system secret store, or the `OANDA_API_TOKEN` GitHub Actions repository secret.
4. Never commit it, paste it into an issue, include it in a screenshot or hard-code it in CI.
5. Revoke and replace a token after accidental disclosure.

The `AppConfig` representation suppresses the token field. The adapter installs the token only in the private HTTP authorization header and never includes it in exceptions.

## Configure shadow mode

```bash
cp .env.example .env
```

```dotenv
FOREX_PROVIDER=oanda
FOREX_MODE=shadow
FOREX_ENABLE_PAPER_ORDERS=false
FOREX_INSTRUMENTS=EUR_USD
OANDA_API_TOKEN=replace-locally
OANDA_ACCOUNT_ID=
OANDA_REST_URL=https://api-fxpractice.oanda.com
```

The account ID may be omitted for read-only operation. The adapter discovers an account visible to the token deterministically. Broker writes remain stricter: `OANDA_ACCOUNT_ID` must be explicitly configured before any Practice order is allowed.

## Read-only verification

```bash
python scripts/smoke_oanda.py
forex-trader sync
```

The smoke output contains only an account-ID suffix, account currency, virtual balance/NAV, price, instrument precision, completed-candle count and open-position state. It never prints the token. `forex-trader sync` then reconciles the Practice transaction cursor before any risk-bearing validation is considered.

Run a strategy evaluation without an order:

```bash
forex-trader demo --instrument EUR_USD
```

For an all-pair current-market diagnostic:

```bash
python scripts/run_practice_campaign.py --all-currency-pairs --max-cycles 1
python scripts/analyze_campaign.py campaign-evidence.jsonl
```

## GitHub Actions staged validation

The `OANDA Practice Validation` workflow is manual (`workflow_dispatch`) and may be dispatched only from `main`. It has three stages:

1. `read-only` — requires only the `OANDA_API_TOKEN` repository secret. It validates configuration, performs the authenticated broker probe, reconciles transaction state, runs one all-currency-pair shadow campaign, analyzes the resulting evidence and uploads the evidence artifact. If `OANDA_ACCOUNT_ID` is not configured, the adapter discovers the authorized Practice account from the token.
2. `round-trip` — requires both `OANDA_API_TOKEN` and `OANDA_ACCOUNT_ID`, plus `confirm_practice_write=true`. It first repeats the software/read-only gates, then executes only the broker-minimum protected open/verify/close probe and reconciles state afterward.
3. `campaign` — requires the same explicit write credentials/confirmation. It performs the read-only and round-trip gates first, then runs the capped Practice campaign and analyzer/promotion report. The workflow input caps campaign cycles at 24 and new orders per cycle at 3; the recommended initial setting remains one new order per cycle.

Authenticated validation runs are serialized with workflow concurrency so two Practice-validation jobs cannot intentionally overlap. Campaign evidence is bound to the exact Actions source SHA through `FOREX_BUILD_REVISION`.

## Explicit broker write-path test

The safest broker-order verification is a broker-minimum round trip. It opens one minimum-size Practice trade with protection and immediately closes that exact trade.

```bash
FOREX_PROVIDER=oanda \
FOREX_MODE=paper \
FOREX_ENABLE_PAPER_ORDERS=true \
python scripts/oanda_round_trip.py
```

The script refuses to run without an explicit account ID or if the selected instrument already has an open position. The underlying round-trip helper always attempts to close a known filled probe trade even if protection verification returns false or raises. An unverified/failed close is treated as a critical reconciliation condition and blocks any claim that the probe succeeded.

The probe does not test strategy profitability; it tests authentication, broker metadata/precision, minimum-size order creation, bounded entry price, dependent protection, fill reconciliation and exact-trade closure.

## Strategy-driven paper orders

After shadow verification and the protected round trip:

```dotenv
FOREX_MODE=paper
FOREX_ENABLE_PAPER_ORDERS=true
OANDA_ACCOUNT_ID=replace-explicitly-for-writes
```

```bash
python scripts/run_practice_campaign.py \
  --execute \
  --all-currency-pairs \
  --max-orders-per-cycle 1 \
  --max-cycles 12
```

All three conditions must be present before a strategy order is sent:

1. operating mode is `paper`;
2. `FOREX_ENABLE_PAPER_ORDERS=true`;
3. the command includes `--execute`.

The engine also requires a tradeable candidate, granted risk authorization, no open position in the instrument and a new atomic execution claim for the signal candle.

## OANDA-specific protections

- REST host must be exactly `https://api-fxpractice.oanda.com`.
- Streaming host must be exactly `https://stream-fxpractice.oanda.com`.
- Instrument metadata defines display precision, pip location, trade-unit precision and size bounds.
- Stops and targets are formatted to broker precision.
- The client uses persistent HTTP connections and bounded retries for read-only requests.
- Market-order and trade-close writes are not blindly retried when the provider outcome may be unknown.
- A definite rejection releases the local execution claim; an unknown outcome retains it to prevent duplicate submission.
- Daily realized P/L is reconstructed from UTC-day transaction pages and included in risk authorization.
- Known fills require dependent protection verification/repair; unresolved protection or close state fails closed.
- Errors do not include the token.

## Current scope

USD-denominated accounts support pairs where USD is the base or quote currency. Crosses such as EUR/GBP remain denied at the risk layer until conversion-rate sizing is implemented.

No authenticated Practice result should be claimed merely because software CI is green. Authentication, broker metadata, pricing, reconciliation, protected round-trip behavior and campaign evidence must be observed through the Practice endpoint itself before promotion decisions are made.
