# 00 — System Vision

## 1. Mission

Build a high-integrity forex scalping platform that combines technical location and confirmation with real-time fundamental context, while remaining broker-agnostic, explainable, testable, and safe to operate.

The objective is not to create a black box that predicts every tick. The objective is to create a decision system that can answer, before every order:

- Why this pair?
- Why this direction?
- Why this location?
- Why now?
- What event or flow could invalidate the trade?
- What is the expected cost?
- Where is the structural invalidation point?
- How much capital is actually at risk?
- What evidence would cause the system not to trade?

## 2. Design philosophy

### 2.1 Context before trigger

A low-timeframe candle pattern is not a complete setup. The system must establish higher-timeframe market structure, major supply and demand, liquidity targets, session phase, macro bias, event risk, and execution conditions before considering a trigger.

### 2.2 Location before indicator

Indicators are secondary measurements. Trades originate from a meaningful location: a fresh zone, a swept liquidity pool, a prior session extreme, a volume node, an opening range, VWAP context, or another pre-declared institutional reference.

### 2.3 Confirmation before commitment

Price touching a zone is an observation, not an order. Unless a setup is explicitly classified as an approved limit-entry archetype, the system waits for rejection, reclaim, displacement, structure shift, order-flow confirmation, or a validated continuation pattern.

### 2.4 Fundamentals are event models, not generic sentiment

“Positive news” is not enough. An economic release must be interpreted relative to consensus, revisions, current central-bank reaction functions, market positioning, and what was already priced. A hawkish statement can strengthen a currency in one regime and fail in another if the market expected more.

### 2.5 Executability is part of the signal

A theoretical edge that disappears after spread, slippage, latency, rejects, or financing is not an edge. The system evaluates executable bid/ask prices and a conservative cost model before admitting a trade.

### 2.6 Every decision must be reproducible

Given the same point-in-time inputs, configuration version, model versions, and random seeds, the decision engine must produce the same decision trace. Human-readable explanations are generated from structured facts, never used as the source of truth.

### 2.7 No autonomous self-modification in live trading

Models may be retrained offline, but a live process cannot change weights, thresholds, or risk limits without a versioned deployment and approval. “Learning” means measuring and proposing; it does not mean silently rewriting the trading policy.

## 3. Market scope

### Initial instruments

The first research universe should focus on liquid majors and selected crosses:

- EUR/USD
- GBP/USD
- USD/JPY
- USD/CHF
- AUD/USD
- USD/CAD
- NZD/USD
- EUR/GBP
- EUR/JPY
- GBP/JPY

The production universe is not automatically the research universe. Each pair must pass spread, liquidity, data-coverage, slippage, and session-quality requirements.

### Initial sessions

The architecture supports 24-hour data ingestion, but active trading should begin with explicitly bounded windows:

- Asian session for range formation and JPY/AUD/NZD-specific events;
- pre-London and London open for European liquidity transitions;
- London–New York overlap for the deepest major-pair liquidity;
- New York macro-release windows;
- optional closing windows only after independent validation.

Session times must be stored in UTC with daylight-saving-aware calendars.

## 4. What “best possible” means

“Best” is defined by system quality, not promotional returns. The target platform should optimize for:

- positive net expectancy after all costs;
- bounded drawdown;
- stability across regimes;
- low probability of catastrophic failure;
- calibrated confidence;
- reproducible decisions;
- provider redundancy;
- minimal look-ahead bias;
- graceful degradation;
- rapid kill-switch response;
- transparent attribution of profit and loss.

## 5. System operating modes

### Research

Historical replay, feature research, labeling, model training, and parameter analysis. No broker writes.

### Shadow

Consumes live data and produces decisions, but never sends orders. Used to compare expected fills with observed prices.

### Paper

Sends orders to a broker’s practice environment or to an internal execution simulator. Paper results must include realistic spread, latency, slippage, and rejection assumptions.

### Limited live

Uses small, capped risk, a restricted instrument list, bounded session windows, and mandatory operator oversight.

### Scaled live

Available only after statistical and operational promotion gates are met. Scaling is gradual and reversible.

### Halted

No new orders. Existing positions are managed according to a predefined emergency policy. The system can enter this mode automatically or manually.

## 6. High-level architecture

The platform is event driven. All inputs become normalized immutable events. Feature services build point-in-time views from those events. Strategy services emit hypotheses, not orders. Risk and execution services are the only components permitted to authorize and route an order.

```text
Sources
  ├── broker executable quotes and account stream
  ├── institutional/futures order-flow proxy
  ├── economic calendar and actual releases
  ├── central-bank communications
  ├── licensed financial news
  ├── cross-asset market data
  └── reference calendars and metadata

Ingestion
  ├── connector lifecycle
  ├── timestamp normalization
  ├── deduplication
  ├── quality scoring
  └── raw payload retention

Intelligence
  ├── fundamental event engine
  ├── news interpretation engine
  ├── technical structure engine
  ├── liquidity and zone engine
  ├── order-flow proxy engine
  ├── regime engine
  └── execution-cost engine

Decision
  ├── currency strength vectors
  ├── pair-relative scoring
  ├── setup state machines
  ├── conflict resolution
  ├── risk gate
  └── order intent

Execution
  ├── broker adapter
  ├── idempotent order submission
  ├── protective-order verification
  ├── fill handling
  ├── reconciliation
  └── emergency flattening

Learning and governance
  ├── immutable decision journal
  ├── attribution
  ├── backtest and replay
  ├── model registry
  ├── approval workflow
  └── operational reporting
```

## 7. Primary hypotheses to test

1. Technical setups taken in the direction of a validated macro/fundamental bias outperform identical technical setups without that alignment.
2. Liquidity-sweep and zone-rejection setups are more robust when confirmed by futures order flow than by broker tick volume alone.
3. Event-specific surprise models outperform generic article sentiment.
4. Trading less during poor spread, stale-data, and conflicting-signal regimes improves net expectancy more than adding entry indicators.
5. Session phase and time-since-event materially change the expected outcome of the same chart pattern.
6. Structure-defined stops and cost-aware position sizing produce more stable risk than fixed-pip stops.
7. Pair-relative currency scoring is superior to assigning a standalone direction to a currency pair without decomposing base and quote drivers.

## 8. Explicit non-goals

- Martingale or loss-recovery sizing.
- Unlimited averaging down.
- Hidden stops.
- Trading every news release.
- Depending on one unverified social-media source.
- Treating an LLM output as an order instruction.
- Using future revisions of economic data in historical simulation.
- Optimizing exclusively for win rate.
- Claiming institutional order flow from decentralized spot candles.
- Going live before paper and operational gates are complete.
