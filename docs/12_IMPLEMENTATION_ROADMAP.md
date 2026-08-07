# 12 — Implementation Roadmap

No executable trading code should be written until Phase 0 decisions and schemas are approved.

## Phase 0 — Specification lock

Deliver:

- approved strategy families;
- public-method interpretation boundary;
- provider shortlist;
- canonical schemas;
- risk policy;
- operating modes;
- repository/module boundaries;
- data-license review;
- architecture decision records.

Definition of done:

- ambiguous terms have measurable definitions;
- no strategy rule relies on “looks strong” without a field or label;
- APPD/session definitions are versioned;
- broker and data roles are separated;
- live promotion gates are documented.

## Phase 1 — Repository and platform foundation

Future code scope:

- packaging;
- configuration;
- environment separation;
- domain schemas;
- event envelope;
- logging;
- test harness;
- CI;
- secret interfaces;
- no broker writes.

Definition of done:

- deterministic schema tests;
- no secrets;
- reproducible environment;
- documented local development.

## Phase 2 — Market-data ingestion

- OANDA practice quotes and candles;
- raw retention;
- normalized quote events;
- bars built from events;
- freshness and gap checks;
- historical backfill.

Definition of done:

- replay matches captured stream;
- bid/ask preserved;
- latency measured;
- data gaps visible.

## Phase 3 — Macro and news ingestion

- Trading Economics calendar stream;
- official-source connectors;
- event deduplication;
- consensus/revision snapshots;
- central-bank document store;
- event-risk calendar.

Definition of done:

- scheduled events are point-in-time;
- actual/consensus/previous/revision are distinct;
- provider latency is measured;
- outage causes conservative degradation.

## Phase 4 — Technical context

- market structure;
- zone detection;
- liquidity map;
- sessions;
- volatility/spread regimes;
- setup labels.

Definition of done:

- algorithms are deterministic;
- zones are never formed with future candles;
- human-label comparison exists;
- every feature has lineage.

## Phase 5 — Futures/order-flow proxy

- licensed CME/vendor connector;
- contract mapping and roll;
- orientation normalization;
- delta, volume profile, VWAP;
- proxy confidence.

Definition of done:

- futures/spot timestamps align;
- inverse pairs are correct;
- roll periods are handled;
- flow-dependent strategies disable on degradation.

## Phase 6 — Fundamental intelligence

- surprise normalization;
- currency vectors;
- statement-delta extraction;
- news event classification;
- cross-asset confirmation;
- abstention.

Definition of done:

- outputs are typed and fact-grounded;
- model confidence is calibrated;
- no model emits orders;
- ambiguous events abstain.

## Phase 7 — Signal fusion and backtester

- policy state machines;
- hard gates;
- regime selection;
- cost model;
- point-in-time simulator;
- walk-forward evaluation;
- reports.

Definition of done:

- no leakage audit findings;
- simple baselines included;
- spread/slippage sensitivity included;
- experiment reproducibility.

## Phase 8 — Shadow system

- live candidates;
- complete decision traces;
- no broker writes;
- expected fill tracking;
- operational dashboards.

Definition of done:

- continuous operation;
- no untraceable decisions;
- provider failures handled;
- alerts tested.

## Phase 9 — Paper execution

- OANDA practice adapter;
- idempotent order lifecycle;
- stops and targets;
- transaction stream;
- reconciliation;
- emergency controls.

Definition of done:

- duplicate protection;
- all positions reconciled;
- missing-stop emergency tested;
- cancel/flatten runbooks tested.

## Phase 10 — Limited live

- tiny capped risk;
- restricted pairs and sessions;
- operator oversight;
- frequent review;
- no automatic scaling.

Definition of done:

- real execution is within stressed assumptions;
- no severe unresolved incidents;
- risk and model gates remain valid;
- explicit approval to continue.

## Phase 11 — Controlled scaling

Scale one dimension at a time:

- risk;
- pairs;
- sessions;
- setup families;
- provider sophistication.

Every increase has rollback criteria.

## Deferred features

- reinforcement learning;
- autonomous parameter updates;
- social-media trading;
- external user accounts;
- copy trading;
- multi-broker smart order routing;
- mobile app;
- full HFT/colocation.

These are deferred because they increase complexity and risk before the core edge is proven.

## Developer execution documents

The phase list above is governed by the detailed build contracts in [`docs/dev/00_DEVELOPER_INDEX.md`](dev/00_DEVELOPER_INDEX.md). The implementation backlog defines epics and exit conditions, while the acceptance matrix defines pass/fail evidence. Developers must not interpret this roadmap as permission to skip provider, data-quality, risk, reconciliation, or recovery work.

