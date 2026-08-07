# Definition of Done

## Any implementation item

- behavior and owner are documented;
- interfaces and failure modes are explicit;
- typed tests cover success, rejection, duplicate, timeout, and restart paths as applicable;
- telemetry and stable error codes exist;
- no secret or licensed payload leaks into fixtures/logs;
- configuration and schema changes are versioned;
- documentation and diagrams are updated;
- CI passes.

## Provider adapter

- official API assumptions cited and verification date recorded;
- sandbox or captured fixtures cover normal and failure responses;
- timeouts, reconnects, heartbeats, gaps, rate limits, and idempotency handled;
- raw payload lineage retained;
- provider SDK types stop at adapter boundary;
- degradation behavior tested.

## Feature

- point-in-time availability defined;
- units, orientation, null behavior, and lookback defined;
- streaming/batch parity tested;
- no-future property tested;
- lineage included in snapshot;
- distribution and drift monitoring defined.

## Strategy policy

- falsifiable setup contract and stable rejection taxonomy;
- policy version and configuration immutable;
- baseline and ablation tests;
- walk-forward results with costs and uncertainty;
- shadow trace reviewed;
- no broker dependency.

## Risk rule

- independent owner review;
- exact calculation and rounding tests;
- restart/reconstruction test;
- authorization contract updated;
- failure defaults to deny;
- operational alert and runbook.

## Execution behavior

- practice broker evidence;
- idempotency and unknown-state tests;
- protection and reconciliation tests;
- cost/latency attribution;
- restart recovery;
- emergency behavior rehearsed.

## Phase promotion

A phase is done only when all relevant acceptance IDs pass, open severity-one/two incidents are resolved, replay evidence is archived, security and data-license checks are current, and named approvers sign the promotion record.
