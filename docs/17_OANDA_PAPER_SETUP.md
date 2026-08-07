# 17 — OANDA Practice Setup

OANDA fxTrade Practice is the initial external paper-trading platform. A demo account uses virtual funds and the REST v20 API supports market data, account state, and order management.

## Create the account and token

1. Open an OANDA demo account for your regulatory division.
2. Sign in to the OANDA HUB or account-management portal.
3. Open **Tools → API** or **My Services → Manage API Access**.
4. Generate a personal access token and copy it immediately.
5. Treat the token as a password. Never place it in Git, a screenshot, a test fixture, or a chat message.
6. The account ID may be copied from the HUB. It may also be omitted; the adapter will select the first account visible to the token.

## Configure locally

```bash
cp .env.example .env
```

Set:

```dotenv
FOREX_PROVIDER=oanda
FOREX_MODE=shadow
FOREX_ENABLE_PAPER_ORDERS=false
OANDA_API_TOKEN=replace-with-token
OANDA_ACCOUNT_ID=replace-with-practice-account-id
OANDA_REST_URL=https://api-fxpractice.oanda.com
```

Run the read-only check:

```bash
python scripts/smoke_oanda.py
```

Then run a shadow decision:

```bash
forex-trader demo --instrument EUR_USD
```

Only after the read-only path succeeds, enable practice-account orders:

```dotenv
FOREX_MODE=paper
FOREX_ENABLE_PAPER_ORDERS=true
```

Execute one protected practice order when a candidate passes every gate:

```bash
forex-trader demo --instrument EUR_USD --execute
```

Run repeated five-minute cycles:

```bash
forex-trader run --interval-seconds 300 --execute
```

The `--execute` flag and `FOREX_ENABLE_PAPER_ORDERS=true` must both be present. The configured endpoint must contain `fxpractice`. These independent gates are intentional.

## Current operational scope

Initial risk sizing supports USD-denominated OANDA Practice accounts trading pairs where USD is either the base or quote currency. Crosses such as EUR/GBP are analyzed but rejected by risk until conversion pricing is implemented.
