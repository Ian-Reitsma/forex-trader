# v0.7.23 — Point-in-Time External Data Plane

v0.7.23 implements the first code tranche from the post-v0.7.22 strategy audit. The release does not claim that licensed market-data subscriptions are bundled, does not promote any new strategy to Practice authority, and does not claim trading profitability. OANDA remains locked to fxTrade Practice.

## What changed

The runtime now has concrete normalized JSON/JSONL adapters for four previously interface-only information planes:

- economic calendar, pre-release consensus, release actuals/revisions, and scheduled event windows;
- real-time/near-real-time news documents with publication and provider-receipt timestamps kept separately;
- cross-asset signals already normalized to the FX pair orientation;
- centralized/institutional order-flow snapshots carrying raw delta/CVD/VWAP/POC/volume/absorption/depth fields plus an explicitly normalized directional-pressure value.

These adapters are deliberately vendor-neutral. They make normalized licensed-provider exports operational inputs without pretending that the repository itself includes a Reuters, Bloomberg, Trading Economics, CME, or other commercial subscription. Provider payloads remain external runtime data and should not be committed.

## Point-in-time rules

Every information family has an explicit availability boundary. Consensus and release data use `available_at`; news uses `received_at`; cross-asset and institutional-flow observations use `observed_at`; scheduled macro events keep `scheduled_at` separate from the timestamp at which that schedule was known. Future records are excluded from a decision snapshot.

Configured order flow is stale after the configured age ceiling and then returns no snapshot. The broker tick-count proxy is explicitly excluded from independent institutional-flow confirmation. It can remain a local technical activity feature but cannot satisfy a policy that requires true flow.

## Runtime wiring

`ExternalContextAggregator` gathers the configured providers at the exact quote timestamp. `ExternalContextFusionPolicy` feeds cross-asset alignment and qualifying institutional flow into the existing independent-confirmation model and stores source/time/health lineage in decision evidence. Provider failures are recorded rather than converted into synthetic evidence.

The economic-calendar adapter is additionally wired into the existing `ScheduledMacroEvent` blackout path. Known high-impact events can therefore block new risk using the same pre-send safety gate already used for durable/manual events. If a configured calendar cannot answer its scheduled-event query, the execution decision fails closed instead of assuming that no event risk exists.

## Strategy authority

The audited catalogue now also contains `flow_divergence:v1` and `vwap_repositioning:v1`. Both are research-only and require institutional flow. They are catalogue entries for research/validation; v0.7.23 does not grant either family automatic signal-generation or broker authority.

`sweep_reclaim:v1` remains the only Practice-authorized strategy family. Zone continuation and breakout/retest remain shadow-only. Post-news continuation remains shadow-only with required flow, and post-news failure remains research-only with required flow.

## Configuration

The optional provider inputs are configured with:

```text
FOREX_ECONOMIC_CALENDAR_PATH=
FOREX_NEWS_PATH=
FOREX_CROSS_ASSET_PATH=
FOREX_ORDER_FLOW_PATH=
FOREX_ORDER_FLOW_MAX_AGE_SECONDS=60
```

The OANDA credential and account configuration are unchanged and remain environment-only:

```text
OANDA_API_TOKEN=
OANDA_ACCOUNT_ID=
OANDA_REST_URL=https://api-fxpractice.oanda.com
OANDA_STREAM_URL=https://stream-fxpractice.oanda.com
```

Secrets and licensed payloads are not source-controlled.

## Still external or evidence-gated

v0.7.23 closes the software integration gap for normalized data but not the acquisition/licensing gap. Actual licensed calendar/news/cross-asset/CME-equivalent feeds still have to be supplied and monitored operationally. Factor/event-cluster portfolio risk beyond the existing currency/correlation/event-blackout controls, technical chart human-label validation, central-bank human truth labels, richer historical executable archives, sustained authenticated Practice evidence, production telemetry/event infrastructure, and research promotion evidence remain separate work/evidence gates.

The distinction matters: an adapter existing in source is not evidence that a vendor feed is connected, current, licensed, or useful. Promotion remains empirical and after-cost.
