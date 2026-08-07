# Domain Model and Aggregates

## 1. Core value objects

- `InstrumentId`: canonical pair such as `EUR_USD` plus provider mappings.
- `CurrencyCode`: ISO currency code.
- `Price`: decimal value, precision, side, and source.
- `Quantity`: signed units with instrument constraints.
- `Money`: amount and currency.
- `UtcInstant`: UTC timestamp with explicit precision.
- `TimeWindow`: inclusive start and exclusive end.
- `PolicyVersion`, `SchemaVersion`, `ModelVersion`, `DatasetVersion`.
- `Confidence`: calibrated probability or bounded score with method and sample support.
- `DataQuality`: freshness, completeness, sequence integrity, and source status.

## 2. Aggregates

### MarketContext

Owns the point-in-time technical state for one instrument and feature horizon. It contains completed bars, active zones, structure state, liquidity map, spread regime, volatility regime, and provider-quality references. It never contains future bars.

### FundamentalContext

Owns currency-level assessments by horizon. It references economic-event snapshots, policy documents, market-implied expectations, cross-asset evidence, model outputs, and uncertainty.

### StrategyEvaluation

Owns one candidate lifecycle from observation through rejection or order-intent eligibility. It records every gate, score, conflict, and policy version. It is immutable after finalization; management decisions create linked evaluations.

### RiskBook

Owns account and portfolio risk state. It aggregates currency legs, pair exposure, event exposure, open risk, realized daily loss, drawdown, margin use, and active halts. Only the risk service mutates it.

### OrderLifecycle

Owns an order intent and all broker acknowledgments, fills, protection, cancellation, closure, and reconciliation state. Provider events are mapped without losing original IDs or payload references.

### PositionLedger

Owns economic positions and accounting state derived from broker transactions. It records lots, average price, realized P/L, financing, commissions, conversion effects, and protective orders.

### ProviderSession

Owns connection state, sequence state, rate-limit state, clock offset, heartbeat history, and degraded-mode status for one provider channel.

## 3. Entity identity

Internal IDs never reuse provider IDs. Every entity stores:

- internal ID;
- provider name;
- provider environment;
- provider account or channel scope where applicable;
- provider ID;
- first-seen event ID;
- correlation and causation IDs.

## 4. Domain events

Representative domain events:

- `QuoteNormalized`
- `CandleClosed`
- `EconomicReleaseObserved`
- `OfficialDocumentObserved`
- `FundamentalAssessmentProduced`
- `TechnicalAssessmentProduced`
- `TradeCandidateProduced`
- `TradeCandidateRejected`
- `RiskAuthorizationGranted`
- `RiskAuthorizationDenied`
- `OrderIntentCreated`
- `BrokerOrderAcknowledged`
- `BrokerOrderFilled`
- `ProtectionConfirmed`
- `ReconciliationMismatchDetected`
- `TradingHaltActivated`
- `PositionClosed`

## 5. Commands

Commands request work and may fail. Events state what occurred.

- `EvaluateInstrument`
- `AuthorizeCandidate`
- `SubmitOrderIntent`
- `CancelOrder`
- `RepairProtection`
- `FlattenAccount`
- `ReconcileAccount`
- `StartReplay`
- `ActivateMode`
- `ActivateHalt`
- `ReleaseHalt`

Each command has an idempotency key, actor, reason, creation time, expiry, and expected policy version.

## 6. Invariants

- An order intent MUST reference an unexpired risk authorization.
- A risk authorization MUST reference a finalized strategy candidate and current portfolio snapshot.
- A strategy candidate cannot be both accepted and rejected.
- A live order cannot use a shadow or paper environment ID.
- A position in paper/live MUST have confirmed protection unless an approved strategy explicitly uses another controlled exit method.
- A broker status `UNKNOWN` prevents duplicate resubmission until reconciliation resolves it.
- A correction never mutates a historical provider observation; it creates a new version linked to the original.
- A feature snapshot references only inputs with event times no later than its `as_of` time.

## 7. Enumerations

Use explicit enums for:

- operating mode;
- data-quality state;
- candidate state;
- risk decision;
- order state;
- position state;
- halt reason;
- event importance;
- surprise direction;
- fundamental horizon;
- technical regime;
- session phase;
- provider health;
- extraction disposition: `SUPPORTED`, `AMBIGUOUS`, `CONTRADICTORY`, `UNSUPPORTED`.

## 8. Serialization boundary

Domain objects are not serialized directly. Contract DTOs map to and from domain types. This prevents database, API, and provider fields from becoming the domain model by accident.
