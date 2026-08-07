# Configuration and Environment Model

## 1. Configuration layers

```text
code defaults
< versioned base configuration
< environment configuration
< deployment-specific non-secret values
< secret references
< temporary operator overrides with expiry
```

Later layers may narrow risk but cannot silently increase live risk beyond an approved policy ceiling.

## 2. Repository layout

```text
config/
  base.yaml
  environments/
    research.yaml
    shadow.yaml
    paper.yaml
    limited-live.yaml
  providers/
    oanda.yaml
    trading-economics.yaml
    cme.yaml
    ibkr.yaml
  strategies/
    sweep-reclaim/v1.yaml
  risk/
    research/v1.yaml
    paper/v1.yaml
    limited-live/v1.yaml
  sessions/
    fx-sessions/v1.yaml
  schemas/
```

Secrets are references such as `secret://broker/oanda/paper/token`, never values.

## 3. Typed settings

Startup validation checks:

- environment and account compatibility;
- required providers and credentials;
- supported instruments and symbol mappings;
- timeframes and watermark consistency;
- risk ceilings;
- strategy-policy versions;
- storage and bus endpoints;
- telemetry requirements;
- live-only protections;
- forbidden combinations.

## 4. Mode isolation

Research, shadow, paper, and live use separate environment identifiers, databases or schemas, object-store prefixes, event subjects/namespaces, broker accounts, and secrets. A paper event cannot be consumed by a live execution worker.

## 5. Policy lifecycle

Configuration used in a decision is immutable and content-addressed. A policy change creates a new version. Deployment activates a version through an approval record. Rollback activates a prior version; history is not rewritten.

## 6. Runtime overrides

Allowed examples: disable instrument, reduce size cap, increase blackout, or halt strategy. Overrides have owner, reason, creation, expiry, scope, and audit event. Overrides cannot enable live mode or increase risk above approved limits.

## 7. Feature flags

Feature flags are typed and environment-scoped. New strategy behavior runs in shadow comparison before it can affect paper/live. A flag cannot bypass schema, risk, or execution gates.

## 8. Validation command

The future repository provides a command that loads all configurations, resolves no secret values, validates cross-file references, prints effective hashes, and fails CI on ambiguity.
