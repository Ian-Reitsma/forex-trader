# Contributing

This repository is documentation-first until the Phase 0 specification lock is approved. Contributions should improve testability, remove ambiguity, or make a future implementation safer and easier to verify.

## Change types

- **Specification change:** changes behavior, schemas, risk rules, state machines, or provider roles. Requires an Architecture Decision Record when costly to reverse.
- **Clarification:** makes an existing decision measurable without changing intent.
- **Research note:** records an unproven hypothesis. It must not be presented as production behavior.
- **Provider update:** changes an external API assumption. It must cite the provider's official documentation and include the verification date.

## Pull-request requirements

Every pull request should state:

1. the problem being solved;
2. documents and contracts changed;
3. whether behavior changes;
4. test or acceptance criteria affected;
5. migration or backward-compatibility impact;
6. risks and unresolved questions.

No strategy claim may be merged without a falsifiable definition. No live-trading behavior may be merged without an independent risk gate and a paper-mode acceptance test.

## Documentation conventions

- Use UTC in all examples.
- Give every event and contract a version.
- Distinguish event time, provider time, receipt time, and persistence time.
- Distinguish executable broker prices from analytical proxy data.
- Use `MUST`, `SHOULD`, and `MAY` as normative terms.
- Keep examples synthetic and never include credentials or account identifiers.

## Decision process

High-cost choices go in `docs/adr/`. The ADR status is `Proposed`, `Accepted`, `Superseded`, or `Rejected`. A superseding ADR links to the prior decision.
