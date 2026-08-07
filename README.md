# Forex Trader

A Practice-only FX research and execution platform built around explicit market location, declared liquidity, structure confirmation, point-in-time macro context, independent portfolio risk, broker-safe execution and auditable validation.

The current codebase is **not** a promise of profitability and is **not** approved for live-money trading. Its purpose is to make the strategy specification, research path, risk path and OANDA Practice execution path consistent enough to measure honestly.

## Current v0.5 architecture

The deployable decision path is structure-first rather than indicator-first:

```text
complete configured lower/higher candles
        +
point-in-time macro/news/central-bank state
        +
market/event/holiday context
        ↓
supply/demand location
        ↓
declared liquidity pool -> sweep/reclaim
        ↓
pivot-derived structure shift -> retest/hold
        ↓
credible structural liquidity/zone target
        ↓
independent fundamental admissibility + spread/cost gate
        ↓
independent stop/currency/margin/correlation risk
        ↓
account lock + fresh size-aware quote + send-time revalidation
        ↓
priceBound + protected OANDA Practice order
        ↓
reconciliation + protection verification + persistent uncertainty halt
```

EMA, RSI and ATR remain useful diagnostics/regime features. They do not substitute for price location, declared liquidity or pivot-derived structure. Spot broker tick activity is explicitly labeled as a low-confidence activity proxy and is **not** represented as centralized footprint/delta order flow.

## Strategy location and liquidity

Runtime technical assessment includes:

- supply/demand zones with proximal/distal bounds, departure strength, touches, penetration, freshness and invalidation;
- 5-p.m.-New-York prior-day highs/lows;
- Sunday-5-p.m.-New-York prior-week highs/lows;
- finalized Asia session highs/lows;
- finalized London and New York 30-minute opening-range highs/lows;
- equal highs/lows, recent external pivots and round-number references;
- explicit liquidity sweep/reclaim events tied to one declared level;
- post-sweep market-structure confirmation and retest/hold state;
- structural invalidation stops and nearest credible opposing liquidity/zone objectives.

Source-time rules prevent a bar from “sweeping” a level it just created. Runtime retains enough lower-timeframe history to reconstruct complete day/session liquidity rather than silently using truncated M5 data.

## Runtime timeframes

The production path can deploy the same timeframe combinations represented by research:

- lower: `M5`, `M10`, `M15`, `M30`;
- higher: `H1`, `H4`.

Configure them with:

```dotenv
FOREX_LOWER_TIMEFRAME=M15
FOREX_HIGHER_TIMEFRAME=H4
```

OANDA candle timestamps are bar starts. Signals are timestamped at the completed lower bar's close so freshness, macro availability and send-time expiry remain no-lookahead across all supported timeframes.

## Fundamentals and events

Macro state is point-in-time and immutable. The runtime supports:

- releases with actual / forecast / previous values;
- revision effects;
- separate policy, inflation, growth, labor and news components;
- component-specific freshness/decay;
- central-bank statement comparison;
- source and availability timestamps;
- scheduled high-impact event blackouts;
- conservative currency holiday blackouts, including ECB/TARGET2 settlement closures.

Fundamentals are independent admissibility/regime evidence. They can reject stale, low-confidence or directionally conflicting setups. They are **not** mixed into the technical quality score with an arbitrary fixed percentage. `TradeCandidate.score` is a quality ranking, not a calibrated probability of profit.

## Risk

Independent risk authorization includes:

- stop-distance sizing from the lower of balance/NAV;
- quote-to-account currency conversion;
- configurable per-trade risk;
- 5-p.m.-New-York marked daily-loss circuit with persistent latch;
- maximum positions and units;
- gross currency-leg exposure;
- single-currency concentration;
- margin reserve;
- signed recent-return correlation veto against existing positions;
- expiring authorization that is rerun on fresh send-time state.

Correlation can only deny duplicated P/L risk. It never increases position size.

## OANDA Practice execution safety

The adapter is locked to OANDA fxTrade Practice endpoints. Broker writes require an explicit `OANDA_ACCOUNT_ID` in addition to the token.

The send path includes:

1. independent risk authorization;
2. account-scoped execution lock;
3. refreshed account and positions;
4. context/event/holiday recheck;
5. size-aware executable quote using OANDA pricing buckets;
6. candidate and risk reauthorization at the fresh price;
7. worst-price `priceBound`;
8. deterministic rejection vs ambiguous-write classification;
9. reconciliation of ambiguous outcomes rather than blind resubmission;
10. dependent stop-loss/take-profit verification;
11. repair attempt and emergency close path if protection is absent;
12. persistent execution-uncertainty halt if broker state cannot be proven.

There is deliberately no live-money endpoint in v0.5.

## Research and backtesting

The research layer is explicitly separate from code coverage and from paper-trading evidence.

Implemented research support includes:

- no-lookahead completed-candle replay;
- gap-through-stop losses;
- spread, entry/exit slippage and decision-delay stress;
- MAE/MFE and ambiguous-bar frequency;
- chronological rolling validation with untouched final holdouts;
- one globally deployable threshold in multi-instrument validation;
- fair-value-gap detection and zone-overlap measurement as a descriptive feature;
- research-only management comparison between the current structural single-target baseline and a 50%-at-1R / breakeven-runner hypothesis.

The management runner is **not** wired into live Practice execution. It must demonstrate incremental after-cost out-of-sample value before receiving runtime authority.

Useful commands:

```bash
python scripts/backtest_oanda.py --instrument EUR_USD --days 90
python scripts/optimize_oanda.py --instrument EUR_USD --days 180
python scripts/validate_oanda.py --instruments EUR_USD,GBP_USD,USD_JPY --days 180
python scripts/compare_management_oanda.py --instrument EUR_USD --days 180
```

OANDA historical candles are midpoint OHLC. Execution stress does not magically reconstruct historical executable bid/ask depth that is absent from the source data.

## Installation

Target Python is 3.13; CI also verifies Python 3.11.

```bash
cd ~/projects
git clone git@github.com:Ian-Reitsma/forex-trader.git
cd forex-trader
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
pip install -e ".[dev]"
cp .env.example .env
pytest --cov=forex_trader --cov-report=term-missing
forex-trader doctor
```

## Offline simulation

Simulation is the default and requires no broker credential.

```bash
forex-trader demo --instrument EUR_USD
```

To exercise the complete simulated paper-order path:

```dotenv
FOREX_PROVIDER=simulation
FOREX_MODE=paper
FOREX_ENABLE_PAPER_ORDERS=true
```

```bash
forex-trader demo --instrument EUR_USD --execute
```

This validates system plumbing. It is not market evidence.

## OANDA fxTrade Practice setup

Create an OANDA Practice/demo account and generate a personal access token through OANDA's API-access controls. Keep the token and account ID local; never paste them into chat or commit them.

```dotenv
FOREX_PROVIDER=oanda
FOREX_MODE=shadow
FOREX_ENABLE_PAPER_ORDERS=false
OANDA_API_TOKEN=your-token
OANDA_ACCOUNT_ID=your-practice-account-id
OANDA_REST_URL=https://api-fxpractice.oanda.com
OANDA_STREAM_URL=https://stream-fxpractice.oanda.com
```

Read-only probe:

```bash
python scripts/smoke_oanda.py
```

Only after the read-only probe succeeds should Practice writes be enabled:

```dotenv
FOREX_MODE=paper
FOREX_ENABLE_PAPER_ORDERS=true
```

```bash
forex-trader doctor
forex-trader demo --instrument EUR_USD --execute
```

A separate gated GitHub Actions workflow exists for authenticated Practice validation. Ordinary pushes do not place broker orders.

## Current validation state

The current v0.5 remediation state has passed on both Python 3.11 and 3.13:

- **197 tests**;
- **87.29% branch-aware coverage**;
- enforced minimum coverage: **85%**;
- install and bytecode compilation;
- `pip check` dependency integrity;
- secret-assignment scan;
- executed offline paper-order smoke.

Authenticated OANDA Practice validation is still pending in this environment because the Practice credentials are not available to GitHub Actions or the local runtime. No real OANDA Practice trade is claimed.

## Deliberate boundaries

The repository still does **not** pretend to have things it does not have:

- no fabricated centralized order flow from spot tick counts;
- no unlicensed production news/economic-calendar scraping;
- no claim that midpoint candle backtests equal executable quote history;
- no automatic live runner/scale-out policy without evidence;
- no profitability or win-rate claim from CI;
- no live-money execution mode.

The next evidence milestone is authenticated OANDA Practice access, followed by a broker-minimum protected round trip, current-market shadow scan, and a sustained multi-regime Practice campaign.

For the detailed runtime boundary see `docs/16_IMPLEMENTATION_STATUS.md`; for the remediation record see `docs/23_AUDIT_REMEDIATION_2026-08-07.md`.
