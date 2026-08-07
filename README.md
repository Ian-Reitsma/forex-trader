# Forex Trader

A runnable, documentation-led forex paper-trading platform that combines multi-timeframe technical structure with currency-level fundamental context, conservative risk authorization, and OANDA fxTrade Practice execution.

The current release is **paper-only**. It contains no live-money endpoint and rejects any OANDA REST host other than `https://api-fxpractice.oanda.com`.

## Implemented system

The working vertical slice is:

```text
M5/H1 completed candles + executable bid/ask
                    +
       timestamped currency fundamentals
                    ↓
          technical assessment
                    ↓
         fundamental differential
                    ↓
       confirmation and cost filters
                    ↓
       independent risk authorization
                    ↓
       shadow decision or paper order
                    ↓
        SQLite audit and decision trace
```

Implemented capabilities include:

- deterministic offline simulation;
- OANDA Practice account discovery, prices, candles, instrument metadata and protected market orders;
- EMA structure, ATR, RSI, trend-strength, liquidity-sweep and displacement analysis;
- strict confirmation, quote freshness, spread and executable reward/risk gates;
- economic-release and news updates to currency-level fundamental state;
- conflict-aware technical/fundamental signal fusion;
- risk sizing from the lower of account balance and NAV;
- score-scaled risk, daily realized-loss checks, position limits and unit caps;
- protection-level validation;
- same-instrument position blocking;
- persistent duplicate-signal protection across process restarts;
- OANDA precision-aware price and unit formatting;
- OANDA read-request retries, ambiguous-order protection and redacted errors;
- read-only and self-closing OANDA Practice verification scripts;
- completion-aware, spread-aware barrier backtesting and score-threshold calibration;
- FastAPI control endpoints, Typer CLI, Docker and GitHub Actions.

## Important performance boundary

The project does not claim a profitable or high-win-rate strategy. Selecting thresholds against synthetic data or the same history used for evaluation would be overfitting. The repository therefore provides chronological training/validation utilities and conservative same-candle execution assumptions. Production claims require historical point-in-time fundamentals, realistic spreads and a later untouched test period.

## Installation

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
pip install -e ".[dev]"
cp .env.example .env
```

Run the complete test suite:

```bash
pytest --cov=forex_trader --cov-report=term-missing
```

Run a safe offline evaluation:

```bash
forex-trader doctor
forex-trader demo --instrument EUR_USD
```

Run a fully simulated paper fill:

```bash
FOREX_PROVIDER=simulation \
FOREX_MODE=paper \
FOREX_ENABLE_PAPER_ORDERS=true \
forex-trader demo --instrument EUR_USD --execute
```

## OANDA Practice

Configure `.env` without committing it:

```dotenv
FOREX_PROVIDER=oanda
FOREX_MODE=shadow
FOREX_ENABLE_PAPER_ORDERS=false
OANDA_API_TOKEN=replace-locally
OANDA_ACCOUNT_ID=
OANDA_REST_URL=https://api-fxpractice.oanda.com
```

Run the read-only probe:

```bash
python scripts/smoke_oanda.py
```

Run a recent-candle technical backtest without placing orders:

```bash
python scripts/backtest_oanda.py
python scripts/optimize_oanda.py --instrument EUR_USD
```

To verify the broker write path with the broker minimum and immediate closure, explicitly enable the paper gates and run:

```bash
FOREX_MODE=paper \
FOREX_ENABLE_PAPER_ORDERS=true \
python scripts/oanda_round_trip.py
```

The round-trip script refuses to run when the selected instrument already has an open position. It opens only the broker minimum and immediately closes the newly created practice trade.

## Control API

```bash
forex-trader serve
curl http://127.0.0.1:8000/health
curl http://127.0.0.1:8000/v1/status
curl -X POST 'http://127.0.0.1:8000/v1/evaluate/EUR_USD?execute=false'
```

## Repository map

| Path | Purpose |
|---|---|
| `src/forex_trader/domain/` | Technicals, fundamentals, fusion, models and risk |
| `src/forex_trader/application/` | Trading orchestration and ports |
| `src/forex_trader/adapters/` | OANDA Practice, synthetic data and paper broker |
| `src/forex_trader/infrastructure/` | Persistent decision and execution claims |
| `src/forex_trader/research/` | Conservative backtesting and threshold calibration |
| `src/forex_trader/api/` | FastAPI control plane |
| `scripts/` | Safe broker probes and research utilities |
| `tests/` | Unit, contract, integration and end-to-end tests |
| `docs/` | Strategy, architecture, operations and implementation specifications |

## Documentation

Start with:

- [Implementation status](docs/16_IMPLEMENTATION_STATUS.md)
- [OANDA Practice setup](docs/17_OANDA_PAPER_SETUP.md)
- [Optimization and validation](docs/18_OPTIMIZATION_VALIDATION.md)
- [Developer implementation index](docs/dev/00_DEVELOPER_INDEX.md)
- [System vision](docs/00_SYSTEM_VISION.md)
- [Strategy specification](docs/02_STRATEGY_SPECIFICATION.md)
- [Risk and governance](docs/08_RISK_CAPITAL_GOVERNANCE.md)
- [Backtesting and validation](docs/09_BACKTESTING_VALIDATION.md)

## Source-method boundary

The strategy is inspired only by publicly described TheForexScalpers concepts such as multi-timeframe structure, supply/demand context, liquidity sweeps, confirmation and session timing. It does not claim to reproduce a private course, paid indicator or undisclosed proprietary formula.

## Safety boundary

Leveraged FX and CFD trading can produce rapid losses. Paper success is not evidence of live profitability. No component can activate live-money trading, and no strategy code can bypass the independent risk policy or the explicit paper-order gates.
