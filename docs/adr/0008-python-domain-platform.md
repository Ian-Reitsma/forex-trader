# ADR 0008 — Python 3.13 Initial Platform

## Status
Proposed

## Decision
Use Python 3.13 with strict typing and locked dependencies for initial implementation.

## Rationale
The project combines asynchronous APIs, numerical analysis, NLP, and research. One language improves parity between research and runtime.

## Consequences
CPU-heavy paths must be profiled and may use vectorized/native libraries or later extraction. Accounting boundaries avoid binary float.
