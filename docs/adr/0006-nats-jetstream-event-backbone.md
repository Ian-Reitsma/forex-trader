# ADR 0006 — NATS JetStream Event Backbone

## Status
Proposed

## Decision
Use NATS JetStream for durable at-least-once events and commands in shared environments; use an in-process implementation for tests and local replay.

## Rationale
It provides simple subjects, durable consumers, replay, and operationally lighter deployment than Kafka for the initial scale.

## Consequences
Consumers must be idempotent. The application depends on an event-bus port so the decision can be revisited.
