# 16 — Implementation Status

## Current release

Version 0.5.0 is a functioning offline-simulation and OANDA fxTrade Practice platform. It remains intentionally Practice/paper-only and contains no live-money endpoint.

```text
completed configured lower/higher candles + executable depth-aware quote
                              +
 point-in-time macro/news/central-bank observations + market/event calendar
                              ↓
 location -> declared liquidity -> sweep -> structure shift -> retest/hold
                              ↓
 structural target + optional fundamental confirmation + execution-cost gate
                              ↓
 independent stop/currency/margin/correlation portfolio risk
                              ↓
 account lock -> fresh depth quote -> send-time revalidation -> priceBound
                              ↓
 protected Practice order / shadow trace
                              ↓
 broker reconciliation + protection verification + persistent uncertainty halt
                              ↓
 Practice promotion metrics + stressed walk-forward validation
```

## Implemented runtime components

- Supply/demand zones with proximal/distal bounds, impulsive departure measurement, touch count, penetration, freshness, invalidation and quality.
- Declared liquidity levels including prior-day extremes, equal highs/lows, recent external swings and round-number references; sweeps are tied to a specific declared level rather than an arbitrary rolling high/low.
- Pivot-derived market-structure state with EMA/RSI/ATR retained as secondary diagnostics rather than independent confirmation votes.
- Explicit sweep -> structure-shift -> retest/hold setup lifecycle, structural invalidation stop and nearest credible liquidity/opposing-zone target.
- Deployable timeframe policy matching the repository research grid: lower M5/M10/M15/M30 and higher H1/H4. Completed-candle signals are timestamped at bar close, not bar start, so freshness/expiry logic remains no-lookahead for every supported timeframe.
- Fair-value-gap detection with mitigation state and supply/demand overlap measurement as a research/confluence feature. FVG is not a mandatory trigger and receives no automatic risk authority.
- DST-aware session phases including Asia, pre-London, London open/continuation, pre-New York, London/New York overlap, New York open/continuation, London fix and rollover.
- Conservative pair holiday blackouts using country calendars plus the ECB/TARGET2 financial calendar. The same hard context gate is checked during initial evaluation and again immediately before submission.
- Broker tick count/activity explicitly labeled as a low-confidence spot-FX activity proxy; it is not presented as centralized bid/ask delta or institutional order flow.
- Immutable macro observations with exact availability timestamps, source metadata, forecasts/actuals/previous values, prior-period revision effects, news and central-bank material.
- Point-in-time fundamental reconstruction that excludes future observations and future-dated seeds, with component-specific freshness/half-life behavior rather than one generic seven-day age.
- Central-bank-specific statement comparison and text handling for directional phrases, negation and uncertainty.
- SQLite persistence for decisions, execution claims, macro history, scheduled events, execution-cost samples, broker transactions, durable cursors, persistent halts, risk-day state and account execution locks.
- OANDA Practice account discovery for read-only access, candles, bounded historical ranges, prices, instrument metadata, positions, currency conversion, protected market orders and trade closing.
- Broker-metadata pip/display/unit precision and margin limits; non-JPY/exotic support no longer relies on a two-case pip heuristic once provider metadata is available.
- Size-aware OANDA pricing buckets, worst-price `priceBound`, deterministic reject versus ambiguous-write handling and broker reconciliation before any retry is considered.
- Dependent stop/take-profit verification after fill, repair attempt when absent, emergency close attempt when protection cannot be verified, and persistent account execution halt for unresolved state.
- Risk sizing from the lower of balance/NAV with quote-to-account currency conversion, marked daily-loss limits, position/unit caps, gross currency exposure, single-currency concentration and margin reserve.
- Signed regime-correlation veto using recent aligned higher-timeframe returns. Correlation can deny duplicated P/L risk and fails closed when an existing position cannot be evaluated; it never increases size.
- Learned session cost profiles and signed slippage samples. Learned limits may tighten but never widen configured spread/slippage ceilings.
- Practice promotion gates requiring sustained multi-day/multi-instrument evidence, positive realized quality metrics and zero unresolved execution/risk halts.
- Backtest/replay support for gap-through-stop losses, configurable spread/slippage/decision-delay stress, MAE/MFE and ambiguous-bar frequency.
- Chronological rolling validation with untouched final holdouts and one globally deployable multi-instrument threshold rather than pair-specific production thresholds.
- CLI, FastAPI, Docker and two-version GitHub Actions verification.

## Current automated validation

The latest v0.5 remediation head passed the complete CI matrix on Python 3.11 and Python 3.13:

- 169 tests passed;
- branch-aware total coverage: 85.94%;
- repository minimum coverage gate: 85%;
- package installation and bytecode compilation passed;
- `pip check` dependency integrity passed;
- secret-assignment scan passed;
- executed offline paper-order smoke test passed on both Python versions.

These checks establish software/invariant quality. They do not establish a profitable trading edge.

## Operator commands

```bash
forex-trader sync
forex-trader sync --stream --max-events 100
forex-trader promotion
python scripts/import_macro_history.py history.jsonl
python scripts/backtest_oanda.py --instrument EUR_USD --days 90
python scripts/optimize_oanda.py --instrument EUR_USD --days 180
python scripts/validate_oanda.py --instruments EUR_USD,GBP_USD,USD_JPY --days 180
```

Runtime timeframe selection is explicit:

```dotenv
FOREX_LOWER_TIMEFRAME=M15
FOREX_HIGHER_TIMEFRAME=H4
```

Only combinations represented by the research grid are accepted. `--technical-only` on research scripts is diagnostic comparison only when point-in-time macro history is unavailable.

## Authenticated OANDA Practice boundary

A deliberately gated GitHub Actions Practice probe was triggered after the software matrix was green. It stopped before making an external OANDA request because this execution environment does not currently contain `OANDA_API_TOKEN` or `OANDA_ACCOUNT_ID` as repository Actions secrets, and no local `.env` containing those credentials is available here.

The code therefore has **not** been represented as having completed a real authenticated OANDA round trip. The next authenticated sequence, once credentials are configured outside chat, is:

1. read-only Practice account/pricing/candle/instrument probe;
2. real broker currency-universe discovery;
3. separately gated broker-minimum protected open -> protection verification -> close round trip;
4. current-market shadow scan;
5. sustained Practice campaign only after the previous steps remain clean.

Secrets must never be pasted into chat or committed to Git.

## Still incomplete / evidence-gated

- Automated licensed economic-calendar collection and consensus snapshots. Scheduled events can already be persisted and enforced once a legitimate feed/import supplies them.
- Automated licensed news ingestion and official central-bank document collection.
- True centralized futures/order-flow ingestion (CME or another legitimate centralized proxy). Spot broker tick activity remains explicitly non-equivalent.
- Historical bid/ask tick reconstruction for every research period; midpoint-candle research can only stress execution assumptions, not reconstruct nonexistent quote history.
- Evidence-backed partial-profit/runner/trailing management policy. The runtime keeps structural stop/target management rather than inventing an unvalidated scale-out formula.
- Sufficient multi-regime, multi-pair untouched historical and sustained OANDA Practice evidence to claim positive expectancy.
- PostgreSQL/TimescaleDB/event-bus deployment for higher-volume production operation.
- Any live-money execution mode.

No win-rate, profitability or capital-readiness claim is supported until the combined system has sufficient point-in-time data, untouched out-of-sample validation and a sustained authenticated Practice campaign.
