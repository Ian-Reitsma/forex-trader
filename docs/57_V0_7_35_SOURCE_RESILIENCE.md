# v0.7.35 JPY/NZD Source Resilience

## Scope

v0.7.35 removes the two remaining live-source failures observed during the Aug. 10, 2026 free-fundamentals sync. It does not lower any strategy, confidence, spread, slippage, risk, drawdown, reconciliation, or broker-write gate.

## JPY

The runtime no longer depends on the Statistics Bureau of Japan English/Japanese HTML layout or on a guessed Bank of Japan publication URL. Both deployable JPY components use the no-key BIS Statistics API:

- policy: `BIS,WS_CBPOL,1.0/M.JP`;
- inflation: `BIS,WS_LONG_CPI,1.0/M.JP.771`.

The BIS central-bank policy-rate dataset is reported directly by member central banks. The BIS long CPI dataset is predominantly sourced from national statistical offices. The runtime consumes the public SDMX v2 CSV representation and stores the exact raw response as official evidence before creating immutable indicator observations.

## NZD

Automated RBNZ retrieval is removed. RBNZ's current website terms restrict automated access without prior written permission, so the runtime does not attempt to bypass its HTTP 403 response.

NZD uses:

- policy: `BIS,WS_CBPOL,1.0/M.NZ`;
- inflation: the latest published Stats NZ `consumers-price-index-<quarter>-<year>-quarter/` release.

The Stats NZ adapter probes predictable quarterly release URLs newest-first. It falls back only when a candidate returns HTTP 404 (for example, a quarter that has ended but whose release has not yet been published). Any other transport, server, or parser failure remains visible and fails that currency rather than silently selecting stale evidence.

## Health semantics

`sync_free_official.py` now distinguishes:

- `healthy`: all attempted currencies succeeded;
- `degraded`: at least one succeeded and at least one failed;
- `unavailable`: no attempted currency succeeded.

A degraded refresh exits non-zero with an accurate degraded-source message. It no longer says that no source succeeded when the JSON report shows partial success.

## Validation

Regression coverage includes:

- no BLS CPI HTML scraping;
- JPY BIS policy + CPI parsing;
- NZD BIS policy + Stats NZ CPI parsing;
- no automated RBNZ request;
- Stats NZ quarter probing may skip a not-yet-published release only on HTTP 404;
- provider health remains degraded on partial success;
- runtime/distribution version identity is v0.7.35.
