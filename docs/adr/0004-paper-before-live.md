# ADR 0004 — Mandatory Shadow and Paper Stages

## Status

Accepted for framework.

## Decision

No strategy may enter live mode without shadow operation, realistic internal simulation, broker-practice execution, reconciliation testing, kill-switch testing, and explicit approval.

## Rationale

Backtests cannot fully reproduce real API failures, slippage, provider delays, or operational mistakes.

## Consequences

- Slower launch.
- Better evidence and safety.
- Live scaling is gradual and reversible.
- Practice and live credentials remain separate.
