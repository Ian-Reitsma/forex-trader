# v0.7.42 Truthful Readiness and Research Instrumentation

## Scope

v0.7.42 is a correctness-of-observability and research-instrumentation release. It does not lower the strategy score, spread, slippage, structural confirmation, reward/risk, portfolio exposure, correlation, macro-factor, drawdown, loss-streak, unit, or position-count gates. It does not enable live-money trading. It does not grant the existing position-management policy broker-write authority.

The release follows the August 12, 2026 Practice diagnosis: the runtime is mechanically healthy after v0.7.41, but the next decision must be based on candidate/exit evidence rather than six dependent realized losses.

## Readiness semantics

`GET /health/ready` remains a narrow liveness/readiness surface for market data and broker reconciliation. Its response now states that scope explicitly and declares that calendar, fundamentals and institutional flow are not requirements of that endpoint. `ready=true` therefore cannot be misread as a trade candidate, risk grant or send-time execution authorization.

`GET /v1/readiness/{instrument}` adds an `eligibility_layers` object. It exposes fundamental preflight confidence, macro-factor classification, scheduled-event repository population for the pair over the next 24 hours, and an explicit `final_trade_eligible: null`. Final eligibility remains a per-decision result of technical, context, spread, risk and send-time execution gates.

An empty scheduled-event repository is reported as `empty`, together with the warning that an empty calendar is not evidence that no macro event exists. v0.7.42 does not manufacture event data or consensus.

## Provider health and capability observability

`TimeframeMappedMarketData` now reports a successful executable quote as healthy market-path evidence instead of automatically presenting the wrapper as degraded because it lacks a separate heartbeat API. If the underlying provider later implements an explicit `health()` contract, that contract remains authoritative.

`GET /v1/providers` exposes a secret-free capability snapshot for the market-data and broker roles. Capability/health evidence is transport observability only; it cannot authorize a strategy or order.

## Loss-breaker API observability

`GET /v1/risk/breaker` exposes the same durable reviewed loss-streak state already available through `scripts/risk_status.py`. It is authenticated and read-only. The endpoint does not clear, reset or review a breaker.

## Authenticated runtime diagnostic

`scripts/capture_runtime_diagnostic.py` replaces ad-hoc unauthenticated curl sweeps for comprehensive captures. It reads `FOREX_API_TOKEN` from the environment, sends it only in the Authorization header, never serializes it, and performs GET-only requests against health, status, runtime, account, positions, provider state, breaker state, promotion, operations, fundamentals, scheduled events and all 28 eight-currency-pair readiness endpoints.

Example:

```bash
python scripts/capture_runtime_diagnostic.py
```

The default output is `diagnostics/runtime-diagnostic-YYYYMMDD-HHMMSS.json`.

## Preregistered candidate horizon study

`scripts/run_candidate_horizon_study.py` evaluates every captured trade candidate, including candidates later denied by risk, at fixed M5 horizons of 6, 12, 24, 48, 72, 144 and 288 bars. These horizons are encoded before outcome inspection. OANDA Practice candles are fetched once per instrument and reused across horizons.

The study reports overall expectancy/R, win/loss/timeout counts, MFE, MAE and estimated cost, plus cohorts by risk disposition, instrument, regime, session and score bucket. The same-bar stop/target assumption remains stop-first conservative. The manifest explicitly prohibits selecting a production horizon from the same sample merely because it looks best.

Example:

```bash
python scripts/run_candidate_horizon_study.py \
  autonomous-decisions-20260810-215103.jsonl \
  --output-dir diagnostics/candidate-horizon-20260812
```

## Position-management shadow

`src/forex_trader/research/runtime_management_shadow.py` replays the existing `RuntimeManagementPolicy` at completed-candle closes without broker write authority. Stop/target touches remain authoritative before close-time management. Event-driven and structure-invalidation branches are not invented when point-in-time evidence is absent.

`scripts/run_position_management_shadow.py` compares the static bracket against the runtime policy for captured candidates with orders by default. It records per-trade delta-R and aggregate expectancy/drawdown evidence. The default static observation horizon is 576 M5 bars (48 hours) so the historical 34-hour position can be represented while the runtime policy itself retains its 30-minute progress check and 120-minute maximum holding time.

Example:

```bash
python scripts/run_position_management_shadow.py \
  autonomous-decisions-20260810-215103.jsonl \
  --output diagnostics/position-management-shadow.json
```

A favorable shadow result is necessary but not sufficient for broker-write promotion. Actual bid/ask path, rollover spread expansion, event state, execution costs, enough independent samples and forward Practice evidence remain required.

## Deliberately not implemented

v0.7.42 does not populate the scheduled-event calendar from guessed dates, synthetic consensus, or unofficial mirrors. It does not claim that current free-official policy/inflation coverage is a complete news/fundamental stack. It does not fabricate institutional flow. Those remain explicit missing capabilities rather than silently substituted data.
