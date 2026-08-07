# Security Threat Model

## 1. Assets

- broker credentials and account authority;
- live capital and positions;
- data-provider credentials and licensed data;
- risk policies and mode controls;
- decision/audit history;
- model and configuration artifacts;
- operator identities;
- raw news and provider payloads.

## 2. Trust boundaries

- internet provider boundary;
- operator/browser boundary;
- event-bus boundary;
- database/object-store boundary;
- secret backend;
- broker execution zone;
- model-provider boundary;
- CI/CD supply chain.

## 3. Primary threats and controls

### Credential theft

Use managed secret storage, short-lived credentials where available, least privilege, separate paper/live credentials, no shell exposure, rotation, and egress restrictions.

### Unauthorized live activation

Separate deployment and account, multi-party approval, mode-specific identity, signed configuration, audit log, and no live credential in non-live environments.

### Forged risk authorization

Risk decisions use trusted storage or signatures, include candidate hash/account/environment/expiry, and are revalidated by execution.

### Duplicate or replayed order

Database uniqueness, provider client IDs, nonce/idempotency key, authorization expiry, and reconciliation before retry.

### Prompt injection in news

Treat documents as untrusted data, isolate instructions from content, use schema-constrained extraction, permit no tool/broker access, retain evidence spans, and fail closed on unsupported output.

### Malicious provider payload

Strict parsing, size limits, decompression limits, field validation, safe logging, timeouts, and sandboxed document processing.

### Supply-chain compromise

Pinned dependencies, scanning, signed artifacts, minimal images, SBOM, protected CI secrets, and restricted release permissions.

### Insider or operator misuse

Role separation, two-person controls for live mode and halt release, immutable audit, reason codes, rate limits, and alerting on sensitive actions.

### Data poisoning

Source authority scoring, cross-source comparison, raw lineage, anomaly detection, training-dataset manifests, and no automatic online learning.

## 4. Broker permissions

Use the minimum broker permissions possible. Research and shadow roles have no broker-write credential. Paper and live execution credentials are accessible only to the execution role. Withdrawal permissions are never required.

## 5. Security tests

- secret scanning and canary-secret tests;
- authorization matrix tests;
- forged/expired risk authorization tests;
- idempotency replay tests;
- payload fuzzing;
- prompt injection corpus;
- dependency and image scans;
- disaster credential rotation drill;
- audit completeness tests.

## 6. Incident response

A suspected compromise triggers global halt, credential revocation, broker verification, evidence preservation, scope assessment, clean rebuild, and explicit reauthorization. Capital protection takes precedence over service uptime.
