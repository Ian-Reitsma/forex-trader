# Audit remediation validation — 2026-08-07

This document records the implementation and validation state of the v0.5 audit-remediation branch. Git remains the source of truth; no Google Drive workflow is used.

## Software validation before broker access

The branch passed the complete GitHub Actions matrix on Python 3.11 and Python 3.13 before authenticated broker validation was intentionally triggered. The CI path includes installation, bytecode compilation, dependency integrity, secret-assignment scanning, the full pytest suite with branch coverage enforcement, and an executed offline paper-trading smoke test.

Coverage is held above the repository's 85% threshold. The threshold was not reduced to obtain a passing build.

## Implemented audit remediations

The runtime now uses explicit supply/demand zones, declared liquidity levels, pivot-derived market structure, sweep/structure-shift/retest setup state, structural liquidity/zone targets, session phases with DST-aware clocks, broker tick counts only as a clearly labeled low-confidence activity proxy, point-in-time fundamental replay, component-specific fundamental decay, central-bank-specific parsing, scheduled macro blackouts, immutable macro/event storage, deterministic import IDs, broker-metadata pip sizing, gross hedged currency exposure, margin-aware risk, latched daily marked-loss halts, account-scoped execution locks, expiring risk authorization, size-aware executable quotes, price bounds, deterministic-reject versus ambiguous-write classification, broker reconciliation, dependent stop/target verification and repair, and persistent execution uncertainty halts.

Research now exposes gap-through-stop losses, spread/slippage/delay stress, MAE/MFE and ambiguous-bar rates, and uses one globally deployable threshold for multi-instrument validation rather than silently selecting a different production policy per pair.

## Practice validation sequence

1. Authenticated read-only OANDA fxPractice probe.
2. Broker currency-instrument discovery using real OANDA metadata.
3. Only after the read-only probe succeeds: a separately gated broker-minimum protected open/verify/close round trip.
4. Current-market strategy scan across the discovered FX universe.
5. Further strategy changes only from observed rejection/candidate/execution evidence; no forced loosening solely to manufacture trade frequency.

The OANDA workflow is practice-only and the API token/account ID are read from repository Actions secrets. Secret values are never printed or committed.
