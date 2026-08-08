# v0.7.12 — Official BLS Provider Adapter

## Purpose

v0.7.12 adds the first concrete official statistical-provider adapter behind the v0.7.11 source-provenance boundary. The goal is trustworthy first-party data acquisition with reproducible request/response provenance. It does not alter strategy thresholds, risk limits, execution authority, or the licensed-consensus boundary.

## Verified provider contract

The adapter targets the U.S. Bureau of Labor Statistics Public Data API v2 endpoint:

`https://api.bls.gov/publicAPI/v2/timeseries/data/`

The endpoint is queried with JSON `POST` because that is the official BLS data-retrieval contract. This POST is a read-only statistical-data query; it is unrelated to broker order submission or any trading write path.

The adapter requires the response-level BLS status `REQUEST_SUCCEEDED`. HTTP 200 alone is not treated as proof of a valid BLS result.

## Request provenance

`OfficialJsonPostClient` canonicalizes each JSON query with sorted keys and compact separators. It retains:

- the exact canonical request bytes;
- SHA-256 of those request bytes;
- the exact raw response bytes through `RawSourcePayload`;
- the independent raw-response SHA-256 and evidence record identity;
- the final official response URL and retrieval time.

Request identity and response identity are intentionally separate. A matching response hash cannot substitute for knowing which query produced it.

The client remains fail-closed on:

- non-OFFICIAL source configuration;
- non-HTTPS or non-allowlisted URLs;
- final-response host escape;
- non-200 HTTP status;
- oversized response payload;
- malformed JSON or non-object JSON roots;
- invalid request hash provenance.

## Conservative BLS query contract

`BlsQuery` intentionally uses conservative unauthenticated/public-query bounds:

- 1-25 unique series IDs;
- uppercase series identifiers only;
- a maximum 10-year inclusive range;
- no BLS registration key or secret embedded in the repository.

These are safety limits for this adapter, not a claim that they represent every maximum available under every BLS registration or API policy.

## Parsed observations

`BlsPublicDataAdapter` retains each returned observation as:

- BLS series ID;
- year;
- period;
- period name;
- `Decimal` value;
- latest flag;
- footnote code/text pairs.

It rejects:

- a BLS-level failed request status;
- missing `Results.series` structure;
- unrequested returned series;
- duplicate returned series;
- omitted requested series;
- malformed observation rows or numeric values;
- malformed footnote structures;
- invalid `responseTime` values.

## Critical point-in-time boundary

A BLS time-series observation is **not automatically an economic-release event**.

The Public Data API supplies historical series observations, but the adapter does not invent:

- an economic-calendar event ID;
- the pre-release consensus;
- the official release instant/availability timestamp for that observation;
- a revision publication timestamp;
- the mapping between a series observation and a specific scheduled CPI/payroll release.

Therefore `BlsPublicDataAdapter` does not emit `OfficialReleaseEvidence` directly. A later scheduled-release adapter/orchestrator must explicitly prove the release schedule and event identity before a BLS value can participate in the v0.7.11 consensus-vs-actual transaction.

This is deliberate protection against look-ahead leakage and false release provenance.

## Tests and CI

All network behavior is tested through deterministic fake transports; CI does not depend on public BLS availability. The BLS and official-JSON modules are first-class Ruff and strict-mypy targets in addition to full pytest/branch coverage and the existing protected simulation paper-order smoke.

## Deliberate non-goals

v0.7.12 does not:

- select a licensed economic-calendar/consensus provider;
- embed any commercial or BLS credential;
- scrape a calendar;
- manufacture release timestamps from BLS historical observations;
- map raw BLS series IDs to tradable event semantics automatically;
- change strategy, risk, Practice, or live-money authority.

## Next P0 milestone

The next provider milestone is official scheduled-document/release discovery and explicit release-calendar mapping, plus a real licensed consensus adapter once a licensed provider is selected and configured outside source control. Those adapters should feed the existing v0.7.11 orchestration rather than bypass it.
