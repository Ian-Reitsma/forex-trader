# Test Strategy

## 1. Test pyramid

- pure domain unit tests;
- property-based tests;
- schema and adapter contract tests;
- database and event-bus integration tests;
- deterministic replay tests;
- provider sandbox tests;
- paper end-to-end tests;
- chaos and recovery tests;
- limited performance tests.

## 2. Mandatory property tests

- price orientation inversion is internally consistent;
- position sizing never exceeds approved risk after rounding;
- duplicate events do not duplicate state;
- event ordering within allowed permutations yields the same final aggregate;
- stop widening cannot occur without a new authorization;
- no feature uses input with `available_at` after decision time;
- P/L ledger sums fills, fees, financing, and conversion exactly;
- replay of a captured run is semantically deterministic.

## 3. Contract tests

Each provider adapter uses captured, redacted fixtures for normal responses, heartbeats, disconnects, malformed payloads, rate limits, retries, and provider-specific error states. Contracts verify mapping without importing SDK types into the domain.

## 4. Golden scenarios

Create synthetic scenarios for:

- clean zone sweep and reclaim;
- sweep without confirmation;
- zone invalidation before entry;
- wide-spread rejection;
- high-impact release blackout;
- release surprise with revision;
- contradictory news sources;
- futures proxy degradation;
- duplicate order response;
- network timeout after broker accepted order;
- partial fill and protection;
- restart with open position;
- missing stop and emergency close;
- daily-loss halt.

Each scenario includes expected events and final state.

## 5. Provider sandbox tests

Tests against practice accounts are isolated, rate-limited, and tagged. They create tiny synthetic orders only when explicitly enabled, then verify transactions, protection, cancellation, closure, and account reconciliation.

## 6. Leakage tests

A dedicated suite shifts availability times, injects revised data early, exposes future candles, and changes fold boundaries. The system must fail or produce different results in the expected direction; silent acceptance is a release blocker.

## 7. Chaos tests

- disconnect each stream;
- delay or duplicate messages;
- pause database writes;
- lose event-bus connection;
- restart each role;
- corrupt one payload;
- skew system clock;
- return broker timeout after acceptance;
- remove news or flow provider;
- restore from backup.

Expected behavior is documented before the test.

## 8. Coverage

Line coverage is secondary. Critical state machines, invariants, risk calculations, and reconciliation branches require explicit branch coverage and mutation testing where practical.
