# Security Policy

The repository currently contains specifications only. Security issues may still exist in architecture, secret-handling guidance, data licensing, or proposed execution controls.

Do not open a public issue containing credentials, broker account identifiers, access tokens, private keys, personally identifiable information, or a working exploit against a deployed system. Use a private disclosure channel configured by the repository owner before implementation begins.

## Non-negotiable implementation controls

- Broker and data-provider secrets never enter source control, logs, traces, prompts, screenshots, or test fixtures.
- Live-order credentials are isolated from research and paper environments.
- A strategy component cannot call a broker adapter directly.
- The risk engine has an independent veto and the execution engine validates authorization freshness.
- All operator actions are authenticated, authorized, and auditable.
- Emergency flatten and cancel-all actions use a separate, tested authorization path.
- Third-party dependencies and container images are pinned and scanned.
- Provider payloads and news text are untrusted input.

See `docs/dev/18_SECURITY_THREAT_MODEL.md` for the implementation threat model.
