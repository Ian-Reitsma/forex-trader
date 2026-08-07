# Forex Trader

A Practice-only FX research and execution platform built around explicit market location, declared liquidity, structure confirmation, point-in-time macro context, independent portfolio risk, broker-safe execution and auditable validation.

The codebase is **not** a promise of profitability and is **not** approved for live-money trading. Its purpose is to keep strategy, research, risk, OANDA Practice execution and evidence consistent enough to measure honestly.

## Current v0.6.2 architecture

```text
complete configured lower/higher candles
        +
point-in-time macro/news/central-bank state
        +
market/event/holiday context
        ↓
supply/demand location
        ↓
declared liquidity -> sweep/reclaim
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
        ↓
implementation-bound cohort-fingerprinted campaign + fail-closed diagnosis
```

EMA, RSI and ATR are secondary diagnostics/regime features. They do not substitute for location, declared liquidity or pivot-derived structure. Spot broker tick activity is explicitly a low-confidence activity proxy and is **not** presented as centralized footprint/delta order flow.

## Strategy location and liquidity

Runtime technical assessment includes supply/demand zones; 5-p.m.-New-York prior-day highs/lows; Sunday-5-p.m. prior-week highs/lows; finalized Asia highs/lows; finalized London/New York opening ranges; equal highs/lows; external pivots; round numbers; explicit sweep/reclaim events; post-sweep structure confirmation; retest/hold state; structural invalidation stops; and nearest credible opposing liquidity/zone objectives.

Source-time rules prevent a bar from “sweeping” a level it created. Runtime retains enough lower-timeframe history to reconstruct complete day/session liquidity rather than silently using truncated M5/M10 data.

## Runtime timeframes

Supported deployable research/runtime combinations are lower `M5/M10/M15/M30` and higher `H1/H4`.

```dotenv
FOREX_LOWER_TIMEFRAME=M15
FOREX_HIGHER_TIMEFRAME=H4
```

OANDA candle timestamps are bar starts. Signals are timestamped at the completed lower bar close so freshness, macro availability and execution expiry remain no-lookahead.

## Fundamentals and events

Runtime supports immutable point-in-time releases with actual/forecast/previous values, revision effects, component-specific decay, central-bank statement comparison, timestamped news context, scheduled event blackouts and conservative currency holiday gates including ECB/TARGET2 closures.

Fundamentals are independent admissibility/regime evidence. They can reject stale, low-confidence or conflicting setups. They are not mixed into technical quality with an arbitrary fixed percentage. `TradeCandidate.score` is a quality ranking, not a calibrated probability of profit.

## Risk and OANDA Practice execution

Independent risk includes stop-distance sizing from lower(balance, NAV), currency conversion, per-trade risk, a persistent 5-p.m.-New-York marked daily-loss circuit, position/unit limits, gross currency exposure, concentration, margin reserve, signed recent-return correlation veto and expiring reauthorization on fresh send-time state. Correlation can deny duplicated P/L risk; it never increases size.

OANDA writes are locked to Practice. The send path includes account-scoped execution locking, refreshed account/positions, context recheck, size-aware pricing buckets, fresh candidate/risk reauthorization, worst-price `priceBound`, deterministic reject vs ambiguous-write classification, reconciliation before retry, dependent stop/take verification, repair and emergency-close handling, plus a persistent uncertainty halt when broker state cannot be proven. There is deliberately no live-money endpoint.

## Evidence-first Practice campaigns

Campaigns are wrappers around `TradingEngine`; they cannot bypass strategy, context, risk or execution safeguards. They cap new Practice submissions per cycle, continue the remaining universe in shadow after the budget is spent, and stop immediately on unresolved broker states.

Each new evidence row carries a `campaign_id`, deterministic secret-free `policy_fingerprint`, JSON-safe `policy_context` and campaign/universe metadata. The fingerprint covers strategy/risk/timeframe/correlation/cost-model configuration plus campaign execution policy. Credentials and account IDs are excluded.

As of v0.6.2, the same cohort identity also includes the authoritative installed implementation version. `forex_trader.__version__`, installed package metadata and FastAPI/OpenAPI all use the same single version source. For exact source-level reproducibility, set `FOREX_BUILD_REVISION` to an immutable Git SHA; GitHub Actions automatically contributes `GITHUB_SHA` when present. Different implementation versions/revisions therefore cannot silently share the same policy fingerprint.

For a local Git deployment:

```bash
export FOREX_BUILD_REVISION="$(git rev-parse HEAD)"
```

When fundamentals are required, **Practice-execution campaigns automatically pre-filter pairs that cannot currently meet the configured fundamental-confidence gate** before spending OANDA candle/pricing requests on guaranteed abstentions. This only saves unnecessary requests; selected pairs still pass the complete quote-time engine pipeline.

Shadow mode scans the full universe by default to diagnose missing fundamental coverage. To use only currently eligible pairs in shadow mode:

```bash
python scripts/run_practice_campaign.py \
  --all-currency-pairs \
  --eligible-only \
  --max-cycles 1
```

After the broker-minimum protected round-trip is verified, start Practice execution with a one-order-per-cycle cap:

```bash
python scripts/run_practice_campaign.py \
  --execute \
  --all-currency-pairs \
  --max-orders-per-cycle 1 \
  --max-cycles 12
```

Analyze one policy cohort:

```bash
python scripts/analyze_campaign.py campaign-evidence.jsonl
```

If a JSONL file contains multiple policy fingerprints, analysis fails instead of blending incompatible experiments. Select one explicitly:

```bash
python scripts/analyze_campaign.py campaign-evidence.jsonl \
  --policy-fingerprint 0123456789abcdef01234567
```

Pre-fingerprint evidence remains readable as the `legacy` cohort. The analyzer also rejects contradictory policy contexts, impossible accounting/status histograms and unknown rejection semantics rather than turning them into a clean strategy result.

## Research and backtesting

Research includes no-lookahead completed-candle replay, gap-through-stop losses, spread/slippage/decision-delay stress, MAE/MFE, ambiguous-bar frequency, chronological rolling validation with untouched holdouts, one globally deployable multi-instrument threshold, FVG location/confluence measurement and research-only management comparison between the structural baseline and partial/breakeven-runner hypotheses.

The management runner is **not** wired into Practice execution. It must demonstrate incremental after-cost out-of-sample value before receiving runtime authority.

```bash
python scripts/backtest_oanda.py --instrument EUR_USD --days 90
python scripts/optimize_oanda.py --instrument EUR_USD --days 180
python scripts/validate_oanda.py --instruments EUR_USD,GBP_USD,USD_JPY --days 180
python scripts/compare_management_oanda.py --instrument EUR_USD --days 180
```

OANDA historical candles are midpoint OHLC. Execution stress does not reconstruct historical executable bid/ask depth absent from the source data.

## Installation and offline validation

Target Python is 3.13; CI also verifies Python 3.11. Package metadata derives its version from `forex_trader.__version__`, preventing build/runtime/API version drift.

```bash
cd ~/projects
git clone git@github.com:Ian-Reitsma/forex-trader.git
cd forex-trader
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
pip install -e ".[dev]"
cp .env.example .env
pytest --cov=forex_trader --cov-branch --cov-report=term-missing
forex-trader doctor
```

Simulation requires no credential:

```bash
forex-trader demo --instrument EUR_USD
```

A full simulated paper fill can be exercised with:

```dotenv
FOREX_PROVIDER=simulation
FOREX_MODE=paper
FOREX_ENABLE_PAPER_ORDERS=true
```

```bash
forex-trader demo --instrument EUR_USD --execute
```

Simulation validates plumbing, not market edge.

## OANDA fxTrade Practice setup

Keep credentials local and never paste them into chat or Git.

```dotenv
FOREX_PROVIDER=oanda
FOREX_MODE=shadow
FOREX_ENABLE_PAPER_ORDERS=false
OANDA_API_TOKEN=your-token
OANDA_ACCOUNT_ID=your-practice-account-id
OANDA_REST_URL=https://api-fxpractice.oanda.com
OANDA_STREAM_URL=https://stream-fxpractice.oanda.com
```

Required progression:

```bash
python scripts/smoke_oanda.py
forex-trader sync
python scripts/run_practice_campaign.py --all-currency-pairs --max-cycles 1
python scripts/analyze_campaign.py campaign-evidence.jsonl
```

Then verify the separately gated broker-minimum protected open/verify/close path. Only after those checks remain clean should `FOREX_MODE=paper` and `FOREX_ENABLE_PAPER_ORDERS=true` be enabled for capped Practice campaigns.

A separate gated GitHub Actions workflow exists for authenticated Practice validation. Ordinary pushes do not place broker orders.

## Current validation state

The exact v0.6.2 code/test head passes on Python 3.11 and Python 3.13:

- **243 tests passed**;
- **87.29% branch-aware coverage**;
- enforced minimum coverage: **85%**;
- fresh dynamic package installation and bytecode compilation passed;
- `pip check` dependency integrity passed;
- secret-assignment scan passed;
- executed offline paper-order smoke passed.

Authenticated OANDA Practice validation is still pending in this environment because Practice credentials are not available to the runtime. No real OANDA Practice trade is claimed.

## Deliberate boundaries

The repository does not fabricate centralized order flow from spot tick counts, substitute unlicensed scraping for production news/economic-calendar feeds, claim midpoint candle backtests equal executable quote history, grant live authority to unvalidated scale-out/runner logic, infer profitability from CI, or expose a live-money execution mode.

The next evidence milestone is authenticated OANDA Practice access, followed by broker reconciliation, a broker-minimum protected round trip, current-market shadow scanning and a sustained multi-regime capped Practice campaign. Strategy or implementation changes produce new evidence identities so before/after data cannot be silently pooled.

See `docs/16_IMPLEMENTATION_STATUS.md` for the runtime boundary and `docs/25_PRACTICE_CAMPAIGN.md` for campaign operations.
