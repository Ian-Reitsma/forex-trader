# v0.7.36 JPY/NZD Source Resilience

## Scope

v0.7.36 hardens the last two free-fundamentals paths exposed by live Aug. 10, 2026 testing. It does not lower any strategy, confidence, spread, slippage, risk, drawdown, reconciliation, or broker-write gate.

## JPY

JPY policy and inflation use machine-readable BIS Statistics API series:

- policy: `BIS,WS_CBPOL,1.0/M.JP`;
- inflation: `BIS,WS_LONG_CPI,1.0/M.JP.771`.

The BIS central-bank policy-rate data set selects the rate that best captures the monetary authority's policy intention and receives daily observations directly from member central banks. Monthly observations are the end-of-month values. The BIS consumer-price data set is predominantly sourced from national statistical offices. Raw public API responses are retained before deterministic indicator observations are created.

This removes the deployable dependency on Bank of Japan HTML-table semantics and Statistics Japan page encoding/layout.

## NZD

NZD policy uses `BIS,WS_CBPOL,1.0/M.NZ`.

NZD inflation continues to use Stats NZ first-party CPI releases. The adapter no longer depends on the Stats NZ topic page being server-rendered. It constructs the predictable quarterly release slugs newest-first and falls back only when a candidate returns HTTP 404, representing a quarter whose release has not yet been published. Transport errors, non-404 HTTP failures and parser failures remain visible instead of silently selecting stale data.

Automated RBNZ access remains absent. The runtime does not attempt to bypass publisher access restrictions.

## Direction semantics

Policy comparisons use the immediately previous monthly BIS observation. An unchanged month therefore contributes neutral policy direction instead of repeatedly comparing the current rate with the last historical rate change.

## Validation

Regression coverage verifies:

- USD remains on the no-key BLS v1 CPI API;
- JPY uses BIS policy and CPI series without BoJ/Statistics Japan HTTP dependencies;
- NZD uses BIS policy plus Stats NZ CPI without RBNZ HTTP requests;
- Stats NZ release probing falls back only on HTTP 404;
- partial provider success remains `degraded` rather than `healthy`;
- runtime/distribution identity is v0.7.36.
