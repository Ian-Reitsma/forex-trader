# v0.7.13 — Official Central-Bank Document Discovery

## Purpose

v0.7.13 adds first-party central-bank document discovery behind the v0.7.11 source-trust boundary. The release discovers candidate official documents and retains feed provenance. It does not yet fetch/normalize document bodies, compare statements, classify stance, or alter trading authority.

## Verified first-party feeds

The release contains explicit feed definitions for:

- Federal Reserve press releases: `https://www.federalreserve.gov/feeds/press_all.xml`
- European Central Bank press releases, speeches, interviews, and press-conference transcripts: `https://www.ecb.europa.eu/rss/press.html`

These URLs are treated as configured first-party publisher contracts, not discovered through scraping or third-party mirrors.

## Raw feed provenance

Every feed poll uses the existing `OfficialSourceClient` and therefore inherits the v0.7.11 controls:

- HTTPS-only allowlisted publisher domains;
- requested and final response URL validation;
- non-200 failure;
- response-size cap;
- timezone-aware retrieval evidence;
- exact raw feed bytes, raw SHA-256, and canonical evidence-record identity.

The feed snapshot's `published_at`/`available_at` are deliberately the poll retrieval time because the XML document as a whole is an observed feed snapshot. Individual entries retain the publisher-provided item timestamp separately.

## Feed parsing

`OfficialFeedDiscovery` supports RSS and Atom structures. Each accepted `DiscoveredOfficialDocument` retains:

- feed ID and source ID;
- publisher item ID/guid;
- title;
- exact first-party document URL;
- publisher-provided item timestamp normalized to UTC;
- feed evidence-record ID;
- feed raw-payload SHA-256;
- optional feed summary;
- deterministic discovery SHA-256.

Duplicate accepted item identities fail closed rather than being silently de-duplicated.

## Link trust

Every item URL is revalidated against the configured first-party source descriptor.

An item that points outside the approved publisher domain is not followed and is not silently discarded. Its URL is retained in `rejected_external_links` so the source-quality anomaly is auditable.

This prevents an official feed from becoming an implicit trust trampoline to an external mirror or compromised link target.

## XML hardening

The parser rejects feed payloads containing `<!DOCTYPE` or `<!ENTITY` declarations before XML parsing. This removes DTD/entity-expansion constructs from the accepted feed surface.

Malformed XML, incorrect RSS/Atom roots, missing required fields, missing timezone information, invalid timestamps, and missing Atom alternate links also fail closed.

## Durable discovery orchestration

`OfficialDocumentDiscoveryOrchestrator` runs every poll through the existing `ProviderPollRunner`, so source health is recorded automatically. The raw feed snapshot is persisted to `SourceEvidenceRepository` and read back successfully before discovered items are returned to downstream code.

The orchestration layer has no broker-write capability.

## Deliberate boundary

Discovery is not document analysis.

v0.7.13 does **not**:

- fetch or store the linked document body;
- infer a document-family lineage from the title;
- compare the document with the prior policy statement;
- label language hawkish/dovish;
- run an LLM or sentiment model;
- turn every central-bank press release into a fundamental trade signal;
- change signal-fusion thresholds, risk limits, Practice authority, or live-money authority.

The feed timestamp also does not substitute for the future document-body retrieval timestamp. Those are separate evidence events.

## CI

The feed parser and discovery orchestrator are explicit Ruff and strict-mypy targets, in addition to deterministic fake-transport tests, full branch-aware pytest coverage, and the existing protected simulation paper-order smoke on Python 3.11 and Python 3.13.

CI does not depend on live Federal Reserve or ECB feed availability.

## Next P0 milestone

The next tranche should fetch accepted first-party document URLs through `OfficialSourceClient`, retain exact raw document bytes, extract deterministic visible text, and maintain explicit same-document-family predecessor lineage before producing sentence/paragraph evidence diffs.

Only after source-backed current-vs-prior evidence exists should stance classification be added. Any NLP layer should emit evidence spans, negation/uncertainty/conditional-language handling, confidence, and model/prompt version rather than replacing the underlying official source record.
