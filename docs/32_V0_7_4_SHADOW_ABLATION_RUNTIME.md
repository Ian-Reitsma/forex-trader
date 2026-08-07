# v0.7.4 — Shadow Ablation Runtime

v0.7.4 adds the authority and immutable-input layer required to wire real component ablations into the existing decision path without creating a broker-write backdoor.

## Explicit masks

The prospective variants map to exactly one disabled component:

```text
full                 -> none
no_fundamentals      -> fundamentals
no_flow              -> flow
no_session           -> session
no_zone_quality      -> zone_quality
no_retest            -> retest
```

`ResearchAblationRequest` rejects a mask that does not match its declared variant.

## Hard shadow boundary

`ShadowAblationRuntime` can be constructed only with `OperatingMode.SHADOW` and `enable_paper_orders=False`.

Paper mode, simulation paper execution and any configuration with broker writes enabled are rejected before the evaluator callback runs. The runtime therefore cannot be reused as an alternate Practice execution path.

## Immutable payload, not just identity

The v0.7.3 evidence layer originally carried an immutable snapshot identity but left the concrete snapshot payload external. v0.7.4 closes that gap.

`FrozenAblationSnapshot` now stores canonical compact/sorted JSON for the point-in-time input payload plus its SHA-256. Construction verifies:

- timezone-aware signal time;
- valid JSON object shape;
- canonical JSON representation;
- SHA-256 format;
- payload hash matches the exact stored bytes.

`from_payload()` normalizes supported primitive/Decimal/datetime/list/mapping inputs into that canonical representation. Every ablation request therefore receives the exact same payload bytes and hash.

## Still intentionally separate from production decisions

The shadow runtime does not itself know how to disable fundamentals, flow, session, zone-quality or retest logic inside the production decision functions. That is the next adapter layer.

This separation is deliberate: the adapter must explicitly prove that each mask alters only the declared component while all other point-in-time inputs remain frozen. Production defaults must remain unchanged.

A correct concrete adapter must also satisfy these invariants:

1. It consumes only `request.snapshot.payload`; it must not refetch candles, quotes, macro state or provider data independently for each variant.
2. `full` must reproduce the normal shadow decision from the same frozen snapshot.
3. A one-component ablation must not silently change another component.
4. Output must remain `ProspectiveAblationDecision`; no broker order object is permitted.
5. Evaluation errors remain paired rows instead of disappearing.
6. Matured results must still pass the v0.7.3 same-snapshot denominator checks before promotion-compatible ablation evidence is emitted.

## Authority

No strategy authority changes in v0.7.4. `sweep_reclaim:v1` remains the only Practice-authorized setup family under `config/system-policy-v0.7.json`. Research `shadow_candidate` status and ablation results remain non-executable.
