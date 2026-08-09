# v0.7.31 — Trading Cockpit Frontend

## Scope

v0.7.31 adds the first full operator-facing frontend to `forex-trader`. The release is deliberately trading-first: the primary route is an observational trading cockpit built around broker account/position state, a TradingView market canvas, immutable decision traces, readiness, risk, promotion evidence and operational telemetry. News and macro intelligence live on a separate `/news` route so they remain available without overwhelming the execution surface.

The frontend does not create a second execution path. There are no browser-side direct-order controls. Any future paper-order control must continue to call the existing guarded engine evaluation/execution path, preserving mode checks, account locking, repricing, hard gates, risk authorization, execution-key claims, reconciliation handling and protection verification.

## Trading desk

The `/` route contains:

- a pair focus matrix driven by recent decision traces;
- broker account NAV, balance, unrealized P/L, margin load and paper-authority state;
- an embedded TradingView advanced chart for the selected OANDA instrument;
- a TradingView-style open-position panel driven by `broker.positions()` rather than synthetic browser state;
- bid/ask/spread and runtime session state;
- a six-stage decision prism mapping the actual runtime sequence: structure → fundamentals → fusion → hard gates → risk → broker/protection;
- an immutable trace inspector exposing candidate geometry, rejection reasons, risk authorization and execution/protection result;
- a filterable decision audit tape;
- promotion/readiness/operations telemetry and a capital-load visualization;
- a historical replay laboratory grounded in the preserved v0.7.30 Jan–Mar development evidence.

The replay laboratory intentionally labels the 0.75 quality / 5 ATR row as a development-selected hypothesis. It shows the negative one-sided 95% expectancy lower bound and negative subgroup stability where recorded. The untouched validation window is shown as locked. PIT macro and centralized-flow stages remain unavailable because the required archives are still absent. No new outcome window is opened by the UI.

## News intelligence

The `/news` route contains:

- point-in-time currency fundamental snapshots;
- macro/news/central-bank observation history;
- a scheduled-event timeline and next-event blackout radar;
- source-boundary explanations that explicitly keep missing institutional flow unavailable rather than substituting broker tick pressure.

This route reads the same protected control-plane state used by the engine. It does not infer retrospective information into historical decisions.

## API additions

The control plane now exposes additional authenticated read models needed by the cockpit:

- `GET /v1/account`
- `GET /v1/positions`
- `GET /v1/market/{instrument}/quote`
- `GET /v1/market/{instrument}/candles`
- `GET /v1/fundamentals/snapshots`
- `GET /v1/events/scheduled`

Existing readiness, status, promotion, decision, operation and fundamental-history routes remain authoritative. The frontend assets are packaged inside the Python distribution and served by FastAPI at `/`, `/news` and `/assets/*`.

## Authentication and browser handling

The page itself may be served without exposing control-plane data. Protected calls continue to require the existing bearer token unless the application was explicitly constructed with the loopback/test escape hatch. The connection drawer stores the bearer credential in browser `sessionStorage` only. It is not placed into source, URLs or persistent `localStorage`.

## Research provenance

The backtesting section displays recorded v0.7.30 evidence from `config/audit-traceability-v0.7.30.json`:

- legacy baseline: 633 trades, -0.0959005565R expectancy, PF 0.8064611417 and -8.775413% fixed-risk return;
- q>=0.75 / <=3 ATR development row: 20 trades, +0.218066R expectancy, PF 1.804;
- q>=0.75 / <=5 ATR selected development row: 39 trades, +0.0487460912R expectancy, PF 1.1386263932, one-sided 95% LCB -0.1795396317R, +0.28234197% fixed-risk return and +0.13807196% production-risk replay return;
- q>=0.75 / <=10 ATR development row: 52 trades, +0.083318R expectancy, PF 1.2076.

These values are presentation of already-open development evidence only. They do not change Practice authority and do not claim validated profitability.

## Authority boundary

OANDA remains fxTrade Practice-only. `sweep_reclaim:v1` remains the only Practice-authorized strategy family. v0.7.31 changes observability and operator ergonomics; it does not authorize the research-only structured-zone threshold, change the v0.7.30 historical evidence, open a new validation window, or grant live-money authority.
