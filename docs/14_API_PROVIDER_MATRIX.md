# 14 — API and Provider Matrix

Provider selection should follow measured requirements, licensing, location, budget, and broker eligibility. This matrix assigns roles; it does not imply endorsement or guaranteed availability.

| Capability | Recommended starting point | Production target / alternatives | Notes |
|---|---|---|---|
| Spot FX execution | OANDA v20 practice then live | Interactive Brokers, another regulated API broker | Keep broker-neutral domain model |
| Executable quotes | Execution broker stream | Secondary independent reference feed | Orders must use broker-executable prices |
| Historical spot data | Broker candles/ticks for baseline | Institutional-grade historical bid/ask | Preserve source identity |
| Futures order flow | Licensed CME FX futures vendor | CME direct, dxFeed, CQG, Rithmic, other licensed feed | Needed for credible centralized delta/depth |
| Institutional spot reference | Optional in research | EBS/CME products, LSEG, other institutional venue/composite | Budget and licensing dependent |
| Economic calendar | Trading Economics | LSEG or another institutional feed plus official sources | Store consensus snapshots and revisions |
| Official releases | Central banks and statistics agencies | Same, with robust direct connectors | Authority source |
| Real-time news | Trading Economics for baseline coverage | LSEG/Reuters machine-readable news or equivalent | General news APIs may be too slow for release trading |
| Central-bank text | Official sites | Licensed news plus official documents | Statement-delta analysis |
| Cross-asset rates | Licensed market-data API | Institutional real-time feed | Needed for yield/rate confirmation |
| NLP inference | Local classifiers plus schema validation | Financial models plus managed LLM adjudicator | No direct order authority |
| Event bus | Evaluate Redpanda/Kafka/NATS | Same based on load/operations | Semantic contracts first |
| Time-series store | Evaluate TimescaleDB/ClickHouse | Based on event volume and query patterns | Do not choose before schemas |
| Object storage | S3-compatible | Managed cloud object store | Raw immutable payloads |
| Metadata/config | PostgreSQL | Managed PostgreSQL | Strong audit and relational integrity |
| Monitoring | OpenTelemetry + metrics/log stack | Managed or self-hosted stack | Trace every decision |

## OANDA role

OANDA’s v20 API publicly documents real-time rates, historical pricing, order operations, account/trade data, and demo/practice access. It is suitable for a first broker adapter and end-to-end paper lifecycle. It is not a global order-flow source.

## Interactive Brokers role

IBKR supports paper and live access through its APIs and can support broader cross-asset expansion. Architecture must account for gateway/session and market-data entitlement requirements.

## Trading Economics role

Trading Economics documents streaming economic-calendar releases and news, with fields for actual, previous, revisions, forecast/consensus, importance, currency, and source. It is appropriate for normalized macro ingestion, but the system should still retain direct official-source references.

## CME/EBS role

CME FX futures and EBS-related products provide centralized or consolidated views that are much more suitable for volume, depth, and institutional-flow proxies than ordinary retail spot candles. Licensing and distribution terms must be reviewed before storage or display.

## Provider evaluation criteria

- regulatory and account eligibility;
- data coverage;
- timestamp precision;
- measured latency;
- uptime;
- replay/history;
- bid/ask/depth availability;
- order types;
- paper environment;
- rate limits;
- licensing and redistribution;
- support;
- cost;
- geographic deployment;
- failure behavior;
- unique IDs and sequencing.

## Buy versus build

Build:

- canonical schemas;
- provider adapters;
- point-in-time storage;
- event interpretation;
- setup policies;
- risk;
- decision traces;
- validation.

Buy:

- licensed raw market data;
- premium news;
- broker execution;
- infrastructure services when operationally cheaper.

Do not attempt to scrape or recreate licensed low-latency feeds from public websites.
