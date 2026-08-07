# ADR 0002 — Futures/Institutional Data for Order Flow

## Status

Accepted for framework.

## Decision

Do not label retail spot tick volume as global order flow. Use CME FX futures, EBS/CME institutional products, or another licensed centralized feed for delta, depth, and volume-profile features. Broker activity can be retained as a low-confidence local feature.

## Rationale

Spot FX is decentralized and fragmented. A single retail broker cannot observe the full market. Centralized futures data provide a defined venue, actual traded volume, and order-book context.

## Consequences

- Additional data cost and licensing.
- Contract mapping and roll logic.
- Proxy confidence must be modeled.
- Flow-required strategies disable when the feed is unavailable.
