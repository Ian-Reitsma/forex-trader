# Performance and Latency Budgets

These are initial engineering budgets for measurement and design, not claims that providers will meet them. Each provider/session receives empirical distributions before paper/live approval.

## 1. Workflow budgets

### Non-news technical decision

- provider event to ingest receipt: measured, no internal target;
- ingest validation/archive enqueue: p99 <= 25 ms;
- normalized event publication: p99 <= 25 ms after receipt;
- incremental feature update: p99 <= 50 ms;
- strategy evaluation: p99 <= 25 ms;
- risk decision: p99 <= 25 ms;
- execution preflight and request construction: p99 <= 50 ms;

External network/broker acknowledgment is measured separately. The system reports end-to-end distributions and does not hide provider latency inside internal metrics.

### Scheduled-release workflow

Correctness and source latency dominate. The architecture must process a normalized release in under 100 ms internally at p99, but the strategy remains disabled until real provider latency and fill behavior prove the use case is viable.

## 2. Throughput assumptions

Initial scope is G10 pairs and a small futures proxy set, not all global instruments. The system is designed for thousands of market events per second with headroom, while OANDA's documented pricing stream is substantially lower per instrument. Load tests use burst multipliers to cover alternate providers.

## 3. Storage budgets

- operational candidate/risk/order query: p95 <= 200 ms;
- latest market/portfolio status query: p95 <= 100 ms;
- full decision trace lookup metadata: p95 <= 300 ms excluding object download;
- event write durability: p99 <= 100 ms in shared environments;
- replay throughput: at least 20x wall-clock for one instrument set on a developer machine, subject to dataset complexity.

## 4. Resource controls

- bounded queues and backpressure;
- per-provider connection and request budgets;
- memory caps for rolling windows;
- chunked historical processing;
- object-store compression;
- database partitioning and retention;
- no unbounded label cardinality in metrics.

## 5. Performance acceptance

Performance tests include normal load, 10x burst, provider reconnect burst, replay catch-up, and database degradation. A missed budget does not justify dropping risk, audit, or persistence steps; it triggers design review or strategy abstention.
