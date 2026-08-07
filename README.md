# Forex Trader

Documentation-first framework for a broker-agnostic forex scalping platform that combines:

- TheForexScalpers-inspired public concepts: multi-timeframe supply and demand, market structure, liquidity sweeps, session timing, confirmation, order-flow context, and structure-defined invalidation.
- Fundamental and news intelligence: economic-calendar surprise analysis, central-bank policy interpretation, macro regime classification, event-aware news sentiment, and cross-asset confirmation.
- Institutional-grade engineering: event sourcing, point-in-time data, deterministic decision traces, realistic simulation, execution-cost modeling, risk gates, circuit breakers, and a paper-to-live promotion process.

This repository intentionally contains **architecture and specifications only**. It does not yet contain executable trading code.

## Non-goal

This project is not designed to maximize trade count or to promise a win rate. Its goal is to build a falsifiable, auditable decision system that trades only when technical location, timing, liquidity behavior, fundamental context, expected execution cost, and portfolio risk align.

## Core design decision

Spot FX is decentralized and fragmented. Broker tick volume is not a market-wide order-flow feed. The system therefore treats:

1. the execution broker as the source of executable bid/ask prices;
2. CME FX futures, EBS/CME spot data, or another institutional feed as the preferred order-flow proxy;
3. economic releases and news as separate event streams;
4. every signal as point-in-time and source-attributed.

## Documentation map

| Document | Purpose |
|---|---|
| [System Vision](docs/00_SYSTEM_VISION.md) | Mission, principles, boundaries, and target operating model |
| [Public Method Interpretation](docs/01_PUBLIC_METHOD_INTERPRETATION.md) | Translation of public TheForexScalpers concepts into testable rules |
| [Strategy Specification](docs/02_STRATEGY_SPECIFICATION.md) | End-to-end setup, entry, management, and exit state machine |
| [Fundamental & News Engine](docs/03_FUNDAMENTAL_NEWS_ENGINE.md) | Macro, calendar, speech, and news-event intelligence |
| [Technical & Order-Flow Engine](docs/04_TECHNICAL_ORDERFLOW_ENGINE.md) | Structure, zones, liquidity, volatility, volume, and futures proxies |
| [Signal Fusion](docs/05_SIGNAL_FUSION_DECISION_ENGINE.md) | Pair scoring, regime weighting, conflict resolution, and trade gating |
| [Data & API Architecture](docs/06_DATA_API_ARCHITECTURE.md) | Event bus, storage, provider adapters, schemas, and data quality |
| [Execution Architecture](docs/07_EXECUTION_BROKER_ARCHITECTURE.md) | Broker abstraction, pre-trade checks, order lifecycle, and reconciliation |
| [Risk & Governance](docs/08_RISK_CAPITAL_GOVERNANCE.md) | Capital allocation, exposure controls, kill switches, and approvals |
| [Backtesting & Validation](docs/09_BACKTESTING_VALIDATION.md) | Point-in-time simulation, leakage prevention, walk-forward tests, and promotion gates |
| [Operations](docs/10_OBSERVABILITY_OPERATIONS.md) | Monitoring, decision traces, incident response, and runbooks |
| [Security & Compliance](docs/11_SECURITY_COMPLIANCE.md) | Secret handling, access controls, data licenses, and auditability |
| [Roadmap](docs/12_IMPLEMENTATION_ROADMAP.md) | Phased build order and definition of done |
| [Repository Structure](docs/13_REPOSITORY_STRUCTURE.md) | Planned module boundaries before code is introduced |
| [Provider Matrix](docs/14_API_PROVIDER_MATRIX.md) | Recommended and alternative API roles |
| [Decision Trace Example](docs/15_DECISION_TRACE_EXAMPLE.md) | Concrete example of how one prospective trade is evaluated |
| [Requirements](docs/requirements.md) | Functional and non-functional requirements |
| [Glossary](docs/glossary.md) | Shared terminology |
| [Architecture decisions](docs/adr/) | Irreversible or high-cost decisions and rationale |
| [Developer Implementation Index](docs/dev/00_DEVELOPER_INDEX.md) | Exact build contracts, services, data models, APIs, tests, runbooks, and backlog |
| [Contract Drafts](docs/contracts/) | Human-reviewable event, market, macro, decision, risk, and execution schemas |
| [System Diagrams](docs/diagrams/) | Context and sequence diagrams for implementation |

## Proposed system layers

```text
Official releases / news / calendars / central banks
                         │
Broker quotes ───────┐   │   ┌──── CME futures / EBS / depth
                     ▼   ▼   ▼
                Ingestion & normalization
                         │
                 Point-in-time event log
                         │
       ┌─────────────────┼─────────────────┐
       ▼                 ▼                 ▼
 Fundamentals      Technicals       Market microstructure
       └─────────────────┼─────────────────┘
                         ▼
             Regime-aware signal fusion
                         ▼
                Risk and cost gate
                         ▼
            Paper or live order router
                         ▼
          Broker reconciliation and ledger
                         ▼
        Analytics, attribution, and learning
```

## Source and intellectual-property boundary

The framework is inspired only by publicly available descriptions of TheForexScalpers' methods. It does not claim to reproduce any private course, paid indicator, proprietary rule set, or undisclosed formula. Public material uses the acronym “APPD” in more than one way; this repository therefore models session phases as configurable, versioned definitions instead of treating one interpretation as canonical.

## Safety boundary

Leveraged FX and CFD trading can cause rapid losses. No component may enter live mode solely because a backtest is profitable. Live access requires data-quality checks, paper performance, risk approval, execution rehearsal, and explicit operator activation.

## Implementation status

The repository is currently **specification complete enough to begin Phase 0 review, not implementation complete**. Start with the [Developer Implementation Index](docs/dev/00_DEVELOPER_INDEX.md), resolve proposed ADRs, and approve the acceptance matrix before adding executable trading code.
