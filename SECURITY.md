# Security Policy

This repository contains a functioning OANDA fxTrade **Practice-only** research and execution platform. It deliberately contains no live-money endpoint. Security issues may affect broker Practice authority, market/macro data integrity, research evidence, control-plane access, or future deployment safety even though real-money execution is unavailable.

Do not open a public issue containing credentials, broker account identifiers, access tokens, private keys, personally identifiable information, or a working exploit against a deployed system. Use a private disclosure channel configured by the repository owner.

## Implemented controls in v0.5

- OANDA REST and stream hosts are hard-locked to fxTrade Practice.
- Broker tokens remain environment/secret-store values and are never intentionally printed or persisted.
- Paper broker writes require an explicit `OANDA_ACCOUNT_ID`, `FOREX_MODE=paper`, `FOREX_ENABLE_PAPER_ORDERS=true`, and an explicit execute path.
- Every market write uses a deterministic setup execution claim, fresh size-aware pricing, an execution `priceBound`, stop/take-profit on fill, and post-fill protection verification.
- Ambiguous broker writes are never blindly retried. Unresolved state latches an account-wide execution halt.
- Account writes are serialized with a durable SQLite execution lock to prevent simultaneous portfolio-risk oversubscription.
- Marked daily-loss state is latched; later profits do not silently re-enable a breached trading day.
- Macro history used by the runtime is point-in-time reconstructed and immutable by observation ID.
- The operator API requires a bearer token when exposed beyond loopback; Docker Compose requires a token and binds only to loopback by default.
- The container runs as an unprivileged user, read-only with `no-new-privileges` in Compose, and exposes a health check.
- CI compiles, checks dependencies, scans credential-shaped assignments, runs the complete branch-coverage test suite on Python 3.11/3.13, and retains pytest diagnostics.

## Controls still required before any future live-money design

- managed short-lived/rotatable secrets and role-specific identities;
- OIDC/identity-aware proxy with viewer/operator/risk-admin role separation rather than a single Practice bearer token;
- multi-party approval for any future live activation or halt release;
- signed immutable release artifacts, SBOM, dependency/container vulnerability scanning and provenance;
- production database migrations, tested backups and restore drills;
- independent market/news/order-flow data integrity monitoring;
- scheduled security and emergency-control drills.

## Non-negotiable boundaries

- Broker and data-provider secrets never enter source control, logs, traces, prompts, screenshots, or test fixtures.
- A language model or news document can never directly call the broker or bypass deterministic risk/execution gates.
- Provider payloads and news text are untrusted input.
- An unresolved broker-write state blocks new account risk.
- A filled position is not considered successfully established until server-side protection is verified.
- Any future live environment must use separate credentials, deployment identity and explicit governance; Practice credentials are not promoted in place.

See `docs/dev/18_SECURITY_THREAT_MODEL.md` for the target threat model and `docs/dev/21_ACCEPTANCE_TEST_MATRIX.md` for broader release controls.
