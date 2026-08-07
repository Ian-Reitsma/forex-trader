# Strategy Policy Engine

## 1. Responsibility

The strategy engine transforms immutable context snapshots into a `TradeCandidate` or a typed rejection. It does not know broker credentials, margin implementation, or provider order objects.

## 2. Policy structure

Each strategy family is a versioned policy with:

```text
scope -> prerequisites -> arming condition -> catalyst -> confirmation
-> entry plan -> invalidation -> target plan -> expiry -> management policy
```

The first implementation supports one family at a time. Recommended first family: higher-timeframe zone plus liquidity sweep and lower-timeframe reclaim/structure confirmation.

## 3. Evaluation state machine

```text
OBSERVING
  -> CONTEXT_ELIGIBLE
  -> LOCATION_ARMED
  -> CATALYST_DETECTED
  -> CONFIRMATION_PENDING
  -> CANDIDATE_PRODUCED
  -> EXPIRED | REJECTED
```

State transitions are driven by events and persisted. Re-evaluating the same event sequence and policy version yields the same transitions.

## 4. Hard prerequisites

Example initial sweep/reclaim policy:

- instrument and session allowlisted;
- required higher-timeframe and execution-timeframe features available;
- zone active and not invalidated;
- spread below pair/session threshold;
- no disallowed event blackout;
- data and clock healthy;
- target liquidity offers minimum gross reward distance;
- portfolio risk is not checked here, but current broad system halt prevents candidate publication.

## 5. Candidate fields

- strategy and policy version;
- instrument and direction;
- setup family;
- anchor zone and liquidity references;
- trigger event;
- confirmation event;
- proposed entry style and valid price range;
- structure-defined stop and buffer method;
- target ladder and rationale;
- candidate expiry;
- expected holding-time class;
- technical and fundamental evidence;
- conflicts;
- required risk checks;
- required execution checks;
- trace reference.

## 6. Score usage

Scores rank candidates within a validated policy. A score does not bypass prerequisites. Weight sets are versioned by regime. The engine preserves component signs, missingness, confidence, and shared lineage to limit double counting.

## 7. Fundamental interaction

Policies declare one of:

- `REQUIRED_ALIGNMENT`
- `ALLOWED_NEUTRAL`
- `COUNTERTREND_SEPARATE_POLICY`
- `EVENT_ONLY`
- `FUNDAMENTAL_NOT_USED`

A general “fundamentals score” cannot silently change meaning across strategy families.

## 8. Expiry and cancellation

Candidates expire by time, price departure, zone invalidation, event-state change, spread deterioration, or provider degradation. Expiry is an event. An expired authorization cannot be used by execution.

## 9. Management decisions

Position management is a separate policy evaluated on current position, original thesis, updated context, costs, and risk. It emits management intents such as hold, reduce, move protection, or close. It cannot widen a protective stop beyond the original risk without a separately authorized risk increase, which is initially prohibited.

## 10. Determinism

The policy receives all nondeterministic values—clock, IDs, random seeds, model outputs—as explicit inputs. No strategy function reads wall-clock time or external APIs directly.

## 11. Baselines

Every sophisticated policy is compared with:

- random direction with same timing and costs;
- session-only breakout;
- simple zone touch;
- simple trend filter;
- no fundamental filter;
- no order-flow filter;
- no-trade baseline.

## 12. Rejection taxonomy

Rejections are stable codes, not prose. Examples:

- `SESSION_NOT_ALLOWED`
- `ZONE_NOT_FRESH`
- `NO_LIQUIDITY_SWEEP`
- `CONFIRMATION_MISSING`
- `FUNDAMENTAL_CONFLICT`
- `EVENT_BLACKOUT`
- `SPREAD_TOO_WIDE`
- `TARGET_TOO_CLOSE`
- `DATA_STALE`
- `FLOW_PROXY_DEGRADED`
- `POLICY_SAMPLE_INSUFFICIENT`

Narrative explanations are rendered from codes and evidence afterward.
