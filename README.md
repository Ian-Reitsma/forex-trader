# Forex Trader

A documentation-led forex paper-trading platform that combines chart technicals, economic-release fundamentals, and news context before independently authorizing risk and routing an order.

The repository now contains a runnable paper-trading MVP plus the full architecture and developer specifications. It does **not** contain a live-trading path.

## What works now

- Deterministic offline market simulator with no credentials.
- OANDA fxTrade Practice integration for account discovery, candles, executable quotes, account summaries, and protected market orders.
- M5/H1 technical analysis using EMA structure, ATR, RSI, liquidity sweeps, displacement, spread gating, structural stops, and 2R targets.
- Currency-level fundamental state updated from economic releases and news text.
- Deterministic signal fusion with explicit abstention reasons.
- Independent stop-distance risk sizing and account limits.
- Shadow mode and paper mode with separate execution gates.
- SQLite decision-trace persistence.
- FastAPI control API, CLI polling runner, Docker support, and GitHub Actions CI.
- 32 automated tests with an enforced 85% coverage floor.

Read [Implementation Status](docs/16_IMPLEMENTATION_STATUS.md) for the exact boundary between working code and later production phases.

## Architecture

```text
Market data provider ── candles / executable quote ──┐
                                                     ├─ technical assessment ─┐
Economic releases / news ─ fundamental state ───────┘                        │
                                                                              ├─ signal fusion
Account snapshot ──────────────────────────────────────────────────────────────┘
                                                                                 │
                                                                                 ▼
                                                                      independent risk gate
                                                                                 │
                                                        ┌────────────────────────┴──────────────────────┐
                                                        ▼                                               ▼
                                                   shadow trace                               protected paper order
                                                        └────────────────────────┬──────────────────────┘
                                                                                 ▼
                                                                          SQLite audit trail
```

## Fastest local start

Python 3.11 or newer is supported; Python 3.13 is the target.

```bash
git clone git@github.com:Ian-Reitsma/forex-trader.git
cd forex-trader
python -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
pip install -e ".[dev]"
cp .env.example .env
pytest --cov=forex_trader --cov-report=term-missing
```

Validate configuration:

```bash
forex-trader doctor
```

Run a deterministic shadow evaluation:

```bash
forex-trader demo --instrument EUR_USD
```

Run an offline simulated paper order:

```bash
FOREX_PROVIDER=simulation \
FOREX_MODE=paper \
FOREX_ENABLE_PAPER_ORDERS=true \
forex-trader demo --instrument EUR_USD --execute
```

Run repeated cycles:

```bash
FOREX_PROVIDER=simulation \
FOREX_MODE=paper \
FOREX_ENABLE_PAPER_ORDERS=true \
forex-trader run --interval-seconds 300 --execute
```

## Free API paper trading: OANDA Practice

Use **OANDA fxTrade Practice** for the external paper account. The demo account uses virtual funds, does not require a deposit, and exposes OANDA's REST v20 market-data and trading API.

1. Create an OANDA demo account for your country.
2. Sign in to the OANDA HUB.
3. Open **Tools → API**. In some account views this appears as **My Services → Manage API Access**.
4. Select **Generate** and copy the personal access token immediately.
5. Copy the practice account ID from the account list, or leave `OANDA_ACCOUNT_ID` blank and the adapter will discover the first account visible to the token.
6. Store the values only in `.env`; `.env` is ignored by Git.

```dotenv
FOREX_PROVIDER=oanda
FOREX_MODE=shadow
FOREX_ENABLE_PAPER_ORDERS=false
FOREX_DATABASE_PATH=./forex_trader.db
FOREX_INSTRUMENTS=EUR_USD,GBP_USD,USD_JPY

OANDA_API_TOKEN=your-personal-access-token
OANDA_ACCOUNT_ID=your-practice-account-id
OANDA_REST_URL=https://api-fxpractice.oanda.com
```

Run a read-only connection test first:

```bash
python scripts/smoke_oanda.py
```

Run the bot in shadow mode:

```bash
forex-trader demo --instrument EUR_USD
```

After the account, quote, and candle checks succeed, permit practice orders:

```dotenv
FOREX_MODE=paper
FOREX_ENABLE_PAPER_ORDERS=true
```

Then:

```bash
forex-trader demo --instrument EUR_USD --execute
```

Both the CLI `--execute` switch and the environment execution gate are required. Paper mode also refuses a non-`fxpractice` OANDA REST URL.

See [OANDA Practice Setup](docs/17_OANDA_PAPER_SETUP.md) for the complete sequence.

## Fundamental and news inputs

The baseline engine maintains a separate state for each currency. A starter state is loaded for EUR, USD, GBP, and JPY so the offline demo is immediately runnable. Production use should replace those values with licensed or official point-in-time feeds.

Start the API:

```bash
forex-trader serve
```

Add an economic release:

```bash
curl -X POST http://127.0.0.1:8000/v1/fundamentals/releases \
  -H 'Content-Type: application/json' \
  -d '{
    "currency": "USD",
    "category": "labor",
    "actual": "250",
    "forecast": "200",
    "previous": "180",
    "higher_is_positive": true,
    "importance": "1"
  }'
```

Add a news observation:

```bash
curl -X POST http://127.0.0.1:8000/v1/fundamentals/news \
  -H 'Content-Type: application/json' \
  -d '{
    "currency": "EUR",
    "headline": "Growth weak as activity contracts",
    "source_weight": "0.8"
  }'
```

Evaluate a pair:

```bash
curl -X POST 'http://127.0.0.1:8000/v1/evaluate/EUR_USD?execute=false'
```

## Safety controls

- The default provider is simulation.
- The default mode is shadow.
- Paper execution is disabled by default.
- The strategy cannot call the broker directly; risk authorization is separate.
- Every practice order includes stop-loss and take-profit instructions.
- Missing or conflicting fundamentals cause abstention when fundamentals are required.
- Wide spreads cause abstention.
- Unsupported account-currency conversions cause risk denial.
- No code selects OANDA's live endpoint.
- Tokens and account identifiers must never be committed.

## Commands

```text
forex-trader doctor        Validate environment and execution gates
forex-trader demo          Evaluate one instrument once
forex-trader cycle         Evaluate every configured instrument once
forex-trader run           Poll continuously or for a finite number of cycles
forex-trader serve         Start the FastAPI control plane
```

## Tests

```bash
pytest
pytest --cov=forex_trader --cov-report=term-missing
```

The suite covers domain validation, technical indicators, long and short setups, release and news processing, fundamental conflicts, spread rejection, risk sizing and limits, simulator fills, OANDA payloads and error mapping, SQLite persistence, polling, CLI behavior, API behavior, and a full paper-order cycle.

## Docker

```bash
docker compose up --build
```

The default container remains in simulation/shadow mode. OANDA credentials are read from the local environment and are not embedded in the image.

## Documentation map

The original design remains under `docs/`. Begin with:

- [System Vision](docs/00_SYSTEM_VISION.md)
- [Strategy Specification](docs/02_STRATEGY_SPECIFICATION.md)
- [Fundamental and News Engine](docs/03_FUNDAMENTAL_NEWS_ENGINE.md)
- [Technical and Order-Flow Engine](docs/04_TECHNICAL_ORDERFLOW_ENGINE.md)
- [Risk and Governance](docs/08_RISK_CAPITAL_GOVERNANCE.md)
- [Developer Implementation Index](docs/dev/00_DEVELOPER_INDEX.md)
- [Implementation Status](docs/16_IMPLEMENTATION_STATUS.md)

## Risk notice

Leveraged foreign-exchange trading can produce rapid losses. Paper results do not establish live expectancy. Do not add live credentials or replace the practice endpoint until the remaining reconciliation, portfolio-risk, point-in-time backtesting, security, and promotion requirements are implemented and independently reviewed.
