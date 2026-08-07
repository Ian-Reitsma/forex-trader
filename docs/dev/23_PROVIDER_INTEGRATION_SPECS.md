# Provider Integration Specifications

Verified against official documentation on 2026-08-06. Provider behavior can change; adapters MUST re-verify during implementation and pin assumptions in tests.

## 1. OANDA v20 — first execution and executable-price adapter

### Roles

- practice and later live execution;
- account-specific executable bid/ask stream;
- instruments and account metadata;
- orders, trades, positions, transactions, and account changes;
- historical candles for baseline/backfill.

### Critical constraints

OANDA's pricing stream supplies at most four prices per second per requested instrument and may omit intermediate prices during rapid movement. Heartbeats are sent every five seconds. Therefore, this adapter is suitable for retail/API scalping research but MUST NOT be described as a full-tick or high-frequency feed.

The transaction stream uses newline-delimited JSON with five-second heartbeats. Store the last transaction ID and use transaction history/account changes to recover after disconnect.

### Adapter modules

- `OandaAuthAdapter`
- `OandaInstrumentCatalogAdapter`
- `OandaPricingStreamAdapter`
- `OandaCandleBackfillAdapter`
- `OandaOrderAdapter`
- `OandaTransactionStreamAdapter`
- `OandaAccountSnapshotAdapter`
- `OandaReconciliationAdapter`

### Required mappings

Preserve OANDA request IDs, client extensions, order/transaction/trade IDs, account environment, price buckets, tradeable status, home-conversion factors, reject reason, and last transaction ID.

### Official references

- Pricing: https://developer.oanda.com/rest-live-v20/pricing-ep/
- Orders: https://developer.oanda.com/rest-live-v20/order-ep/
- Transactions: https://developer.oanda.com/rest-live-v20/transaction-ep/
- Accounts: https://developer.oanda.com/rest-live-v20/account-ep/

## 2. Trading Economics — calendar and broad news normalization

### Roles

- future economic calendar snapshots;
- live calendar releases over WebSocket;
- broad news stream;
- optional cross-asset and economic time series.

The integration stores plan/entitlement metadata and does not assume all endpoints are licensed. Calendar streaming and news streaming are separate channels. REST backfill and streaming observations reconcile to canonical event IDs.

### Modules

- `TECalendarBackfillAdapter`
- `TECalendarStreamAdapter`
- `TENewsStreamAdapter`
- `TEIndicatorHistoryAdapter`
- `TEProviderHealthAdapter`

### Official references

- https://docs.tradingeconomics.com/economic_calendar/streaming/
- https://docs.tradingeconomics.com/news/streaming/
- https://docs.tradingeconomics.com/get_started/

## 3. CME Group — analytical futures/order-flow proxy

### Roles

- futures reference data;
- top-of-book prices, trades, and statistics through the real-time futures/options WebSocket API;
- historical data through DataMine;
- optional FX Tape+ consolidated FX view.

CME's cloud real-time futures/options API top-of-book messages are documented as conflated to 500 ms. This is not full-depth message-by-message order flow. If the strategy requires depth, queue position, or native incremental book reconstruction, procure the appropriate licensed feed/vendor and create a separate capability class.

### Capability levels

- `TOP_OF_BOOK`: bid/ask/trades/statistics;
- `CONSOLIDATED_FX`: Tape+ where licensed;
- `FULL_DEPTH`: separate licensed feed, not assumed;
- `HISTORICAL`: DataMine or approved vendor.

Policies declare minimum capability. Missing capability rejects the flow-dependent policy.

### Official references

- https://www.cmegroup.com/market-data/market-data-api.html
- https://www.cmegroup.com/market-data/real-time-futures-and-options-data-api.html

## 4. Interactive Brokers — optional second broker/multi-asset adapter

IBKR remains an alternative, not part of the initial critical path. Its unified Web API includes HTTP and WebSocket workflows, session constraints, market-data entitlements, and documented pacing. Official documentation currently describes a global limit of 10 requests per second per authenticated username and one brokerage session per username. The April 2026 changelog states that WebSocket market-data `smd` requests terminate after ten minutes and require renewal. These facts require adapter-level scheduling and should not leak into domain code.

Paper use still requires a fully open and funded live account according to IBKR's official documentation.

### Official references

- https://ibkrcampus.com/campus/ibkr-api-page/webapi-doc/
- https://ibkrcampus.com/campus/ibkr-api-page/web-api-changelog/
- https://ibkrcampus.com/campus/ibkr-api-page/order-types/

## 5. Official-source connectors

Central banks and statistical agencies are authoritative for documents and final releases. Build a generic source connector framework with per-site adapters, change detection, content hashing, robots/license review, and fallback to metadata-only references where redistribution is restricted.

## 6. Capability matrix contract

Each provider adapter publishes capabilities, environment, entitlements, instruments, latency class, data depth, history availability, sequence support, and current health. Strategy policies depend on capabilities, not provider names.
