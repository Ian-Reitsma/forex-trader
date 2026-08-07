# 17 — OANDA Practice Setup

OANDA fxTrade Practice is the initial external paper-trading platform. The adapter is locked to the practice REST host and cannot be pointed at OANDA's live-money REST host through configuration.

## Credential handling

1. Create an OANDA demo account for the applicable regulatory division.
2. In the OANDA account portal, open **Manage API Access** and generate a personal access token.
3. Store the token only in a local `.env` file or an operating-system secret store.
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

The account ID may be omitted. The adapter discovers the first account visible to the token in deterministic ID order.

## Read-only verification

```bash
python scripts/smoke_oanda.py
```

The output contains only an account-ID suffix, account currency, virtual balance/NAV, price, instrument precision, completed-candle count and open-position state. It never prints the token.

Run a strategy evaluation without an order:

```bash
forex-trader demo --instrument EUR_USD
```

## Explicit broker write-path test

The safest broker-order verification is a broker-minimum round trip. It opens one minimum-size practice trade with protection and immediately closes that exact trade.

```bash
FOREX_PROVIDER=oanda \
FOREX_MODE=paper \
FOREX_ENABLE_PAPER_ORDERS=true \
python scripts/oanda_round_trip.py
```

The script refuses to run if the selected instrument already has an open position. It does not test strategy profitability; it tests authentication, precision, order creation, attached protection, fill parsing and trade closure.

## Strategy-driven paper orders

After shadow verification:

```dotenv
FOREX_MODE=paper
FOREX_ENABLE_PAPER_ORDERS=true
```

```bash
forex-trader demo --instrument EUR_USD --execute
forex-trader run --interval-seconds 300 --execute
```

All three conditions must be present before an order is sent:

1. operating mode is `paper`;
2. `FOREX_ENABLE_PAPER_ORDERS=true`;
3. the command includes `--execute`.

The engine also requires a tradeable candidate, granted risk authorization, no open position in the instrument and a new atomic execution claim for the signal candle.

## OANDA-specific protections

- REST host must be exactly `https://api-fxpractice.oanda.com`.
- Instrument metadata defines display precision, pip location, trade-unit precision and size bounds.
- Stops and targets are formatted to broker precision.
- The client uses persistent HTTP connections and bounded retries for read-only requests.
- Market-order and trade-close writes are not blindly retried when the provider outcome may be unknown.
- A definite rejection releases the local execution claim; an unknown outcome retains it to prevent duplicate submission.
- Daily realized P/L is reconstructed from UTC-day transaction pages and included in risk authorization.
- Errors do not include the token.

## Current scope

USD-denominated accounts support pairs where USD is the base or quote currency. Crosses such as EUR/GBP remain denied at the risk layer until conversion-rate sizing is implemented.
