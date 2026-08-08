# v0.7.11 — Macro Source Provenance and Orchestration

## Purpose

v0.7.11 closes the first P0 gap between the strategy's point-in-time fundamental model and real external macro evidence. The release is about source integrity and orchestration, not changing trade frequency or loosening strategy/risk gates.

This release was rebuilt directly from the verified GitHub `main` state after an audit found that earlier claimed v0.7.11-v0.7.13 branches/PRs did not actually exist in the repository. The authoritative predecessor is therefore the merged v0.7.10 code state, not an invented intermediate release history.

## Trust boundary

Every raw macro source is explicitly one of:

- `OFFICIAL`: a central bank, government statistical agency, or other first-party publisher of the actual release/document.
- `LICENSED`: a separately contracted calendar/consensus source that is allowed to provide pre-release market consensus.

The repository intentionally does **not** hard-code a commercial calendar vendor, API key, account identifier, or scraped substitute. Tests use an obviously synthetic licensed-domain descriptor only to prove the interface. A real licensed provider must be configured outside source control and must satisfy the same evidence contract.

Official acquisition is HTTPS-only and host-allowlisted. The requested URL and the final response URL must both remain within the approved publisher domain. Non-200 responses, hostile host escapes, invalid timestamps, hash mismatches, and oversized payloads fail closed.

## Raw evidence contract

`RawSourcePayload` retains:

- source ID, publisher, and authority class;
- exact URL and content type;
- `published_at`, `available_at`, and `retrieved_at` timestamps;
- raw response bytes;
- SHA-256 of those bytes;
- a second canonical `record_id` SHA-256 that binds payload identity to retrieval provenance.

This separates content identity from observation identity. The same bytes retrieved at different times have the same payload hash but different evidence-record IDs.

## Point-in-time event contract

`EconomicEventMapping` binds one logical indicator/currency event to exactly one licensed consensus source and one official actual source, with explicit directionality, unit, and importance.

`LicensedConsensusEvidence` must be available no later than the scheduled release. `OfficialReleaseEvidence` cannot become available before the scheduled release. Source IDs, scheduled timestamps, indicator identity, and currency identity must match before `calculate_release_surprise` is allowed to run.

This prevents post-release information from masquerading as consensus and prevents an official actual from being joined to the wrong scheduled event.

## Durable source evidence

`SourceEvidenceRepository` adds append-oriented SQLite durability for:

- raw macro source payloads;
- point-in-time source retrieval;
- provider-health observations.

The ingestion transaction verifies that both licensed consensus evidence and official actual evidence can be read back from durable storage before a `MacroObservation` is emitted.

## Provider health

`ProviderPollRunner` automatically records source state around every orchestrated provider call:

- success -> `HEALTHY`;
- explicit rate limit -> `DEGRADED`, `rate_limited=true`, then re-raise;
- provider/parser exception -> `UNAVAILABLE`, then re-raise.

Health observations are point-in-time and become unavailable when stale.

## Orchestration

`MacroIngestionOrchestrator` enforces the event lifecycle:

1. poll licensed consensus no later than the scheduled release;
2. poll the official actual no earlier than the scheduled release;
3. verify provider IDs against the mapping;
4. validate the consensus/actual pair;
5. durably retain both raw evidence records;
6. create a deterministic release observation identity from the mapping and the two raw evidence IDs;
7. append the existing `MacroObservation.release` contract through the supplied observation sink.

No broker order API is present in this path.

## Event-specific readiness

`MacroReadinessEvaluator` makes provider readiness event-specific instead of generic:

- pre-release: the mapped licensed consensus source is required;
- at/after release: both the mapped consensus source and mapped official source are required;
- missing, stale, or unavailable required sources fail readiness;
- a required source that is rate-limited also fails readiness explicitly.

Other quote/candle/account/reconciliation gates remain owned by the existing system readiness model.

## v0.7.10 regression repair included in this release

The repository audit also found release-state drift inherited from v0.7.10: the family-wise ablation implementation was already merged, while several tests and the runtime version identity still reflected v0.7.9 behavior. v0.7.11 aligns those regressions with the already-merged simultaneous family-wise contract. It does not weaken family-wise promotion requirements: individual component intervals remain readable but are insufficient for a five-component promotion decision.

## Deliberate non-goals

v0.7.11 does not:

- select or embed a licensed economic-calendar vendor;
- scrape an unlicensed calendar/news source;
- infer consensus from an official actual;
- add central-bank stance NLP;
- claim institutional order flow from spot broker ticks;
- change strategy thresholds, risk limits, setup authority, Practice authority, or live-money authority;
- claim authenticated OANDA Practice success.

## Next P0 milestone

The next data milestone is concrete provider integration behind these interfaces: a licensed consensus/calendar adapter and official scheduled-release/document adapters, with secrets external to Git, exact source freshness propagated into campaign/decision evidence, and real prospective evidence accumulated before any strategy gate is reconsidered.
