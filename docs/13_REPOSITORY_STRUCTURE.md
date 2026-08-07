# 13 — Planned Repository Structure

This is the intended future module layout. Directories are conceptual until implementation begins.

```text
forex-trader/
├── README.md
├── docs/
│   ├── 00_SYSTEM_VISION.md
│   ├── 01_PUBLIC_METHOD_INTERPRETATION.md
│   ├── 02_STRATEGY_SPECIFICATION.md
│   ├── 03_FUNDAMENTAL_NEWS_ENGINE.md
│   ├── 04_TECHNICAL_ORDERFLOW_ENGINE.md
│   ├── 05_SIGNAL_FUSION_DECISION_ENGINE.md
│   ├── 06_DATA_API_ARCHITECTURE.md
│   ├── 07_EXECUTION_BROKER_ARCHITECTURE.md
│   ├── 08_RISK_CAPITAL_GOVERNANCE.md
│   ├── 09_BACKTESTING_VALIDATION.md
│   ├── 10_OBSERVABILITY_OPERATIONS.md
│   ├── 11_SECURITY_COMPLIANCE.md
│   ├── 12_IMPLEMENTATION_ROADMAP.md
│   ├── 13_REPOSITORY_STRUCTURE.md
│   ├── 14_API_PROVIDER_MATRIX.md
│   ├── 15_DECISION_TRACE_EXAMPLE.md
│   ├── requirements.md
│   ├── glossary.md
│   └── adr/
├── src/
│   └── forex_trader/
│       ├── domain/
│       ├── ingestion/
│       │   ├── brokers/
│       │   ├── market_data/
│       │   ├── macro/
│       │   ├── news/
│       │   └── reference/
│       ├── normalization/
│       ├── features/
│       │   ├── technical/
│       │   ├── orderflow/
│       │   ├── fundamental/
│       │   ├── cross_asset/
│       │   └── regime/
│       ├── strategy/
│       │   ├── setups/
│       │   ├── fusion/
│       │   └── policy/
│       ├── risk/
│       ├── execution/
│       ├── portfolio/
│       ├── backtest/
│       ├── observability/
│       └── operations/
├── tests/
│   ├── unit/
│   ├── contract/
│   ├── replay/
│   ├── backtest/
│   ├── integration/
│   └── chaos/
├── configs/
│   ├── base/
│   ├── research/
│   ├── shadow/
│   ├── paper/
│   └── live/
├── schemas/
├── notebooks/
│   └── research_only/
├── scripts/
├── infra/
└── reports/
```

## Boundary rules

### `domain`

Pure business concepts and schemas. No provider SDK imports.

### `ingestion`

Provider-specific connectors. They produce canonical events and cannot decide trades.

### `features`

Point-in-time feature computation. No order submission.

### `strategy`

Setup state machines and signal fusion. Emits trade candidates only.

### `risk`

The sole authority for capital and portfolio approval.

### `execution`

The sole authority for broker writes. It cannot alter strategy evidence.

### `backtest`

Uses the same domain policies and feature logic where practical, but simulated time and execution adapters.

### `observability`

Metrics, traces, logs, and reports. Read-only regarding trading state.

## Dependency direction

```text
provider adapters → domain contracts ← strategy/risk/execution
```

The domain cannot depend on provider SDKs. Strategy cannot import a broker client. Execution cannot import a language model as an order-deciding component.

## Configuration

Configuration is versioned, typed, and environment-specific. Live settings cannot inherit unsafe research defaults silently.

## Tests

- Unit: deterministic calculations.
- Contract: provider payload and adapter behavior.
- Replay: captured event reproduction.
- Backtest: no leakage and execution realism.
- Integration: paper broker and data services.
- Chaos: disconnects, duplicates, stale data, partial fills, clock issues.

## Concrete implementation layout

```text
forex-trader/
  README.md
  CONTRIBUTING.md
  SECURITY.md
  pyproject.toml                 # added when implementation starts
  uv.lock                        # added and committed when implementation starts
  config/
    base.yaml
    environments/
    providers/
    strategies/
    risk/
    sessions/
    schemas/
  contracts/                     # generated JSON Schema / AsyncAPI / OpenAPI
  docs/
    dev/
    contracts/
    diagrams/
    adr/
  migrations/
  src/forex_trader/
    domain/
    application/
    adapters/
    infrastructure/
    services/
    api/
    research/
  tests/
    unit/
    property/
    contract/
    integration/
    replay/
    provider_sandbox/
    chaos/
    performance/
    fixtures/
  deployments/
    compose/
    shadow/
    paper/
    limited_live/
  scripts/                       # operational wrappers, not business logic
```

The repository remains documentation-only until Phase 0 approval. The empty implementation paths above are not created merely to make the project appear complete.

