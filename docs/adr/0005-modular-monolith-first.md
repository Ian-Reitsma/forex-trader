# ADR 0005 — Modular Monolith First

## Status
Accepted

## Decision
Build one codebase with strict modules and multiple process roles before splitting into independent services.

## Rationale
The system needs deterministic behavior and shared contracts more than network boundaries. Premature microservices increase failure modes and make replay parity harder.

## Consequences
Boundaries are enforced by imports, ports, contracts, and process composition. A module may be extracted later when scaling or independent deployment proves necessary.
