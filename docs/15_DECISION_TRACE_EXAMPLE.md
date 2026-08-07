# 15 — Example Decision Trace

This is a conceptual example, not a trading recommendation.

## Scenario

Pair: EUR/USD  
Session: London–New York overlap  
Setup family: post-release sweep and reclaim continuation  
Mode: paper

## 1. Pre-event context

- Daily structure: upward but near a higher-timeframe supply zone.
- 1H structure: range.
- Asian high and prior-day high are close together.
- A fresh 15M demand zone sits below the pre-release range.
- U.S. inflation release is scheduled.
- Broker spread is normal.
- CME Euro FX futures flow feed is healthy.
- Existing portfolio has no EUR or USD concentration.

State: `CONTEXT_ELIGIBLE`.

## 2. Event

The release arrives through the calendar stream.

- Actual inflation is above consensus.
- Previous value is revised slightly higher.
- Initial normalized surprise supports USD.
- U.S. short-term yields rise.
- EUR/USD drops rapidly.
- Spread widens above the allowed entry threshold.

State: `EVENT_BLACKOUT`; no immediate order.

## 3. Location interaction

Price sweeps below the Asian low into the predeclared 15M demand zone. The excursion is within the tested sweep bound. Price re-enters the Asian range.

State: `LOCATION_ARMED`.

## 4. Flow and structure

- Euro FX futures show heavy sell volume but limited further price progress.
- Delta begins to diverge.
- A 1M displacement candle closes back above internal structure.
- Broker spread returns to normal.
- U.S. yields remain higher, which conflicts with the long EUR/USD reversal.

State: `CONFIRMATION_PENDING`.

## 5. Fusion

Evidence:

- technical location: strong;
- sweep/reclaim: strong;
- flow reversal: moderate;
- fundamental alignment: negative;
- session: strong;
- execution quality: restored;
- target distance: adequate.

Policy result:

The ordinary trend-aligned reversal policy rejects because fundamentals conflict. A separately validated “news overreaction failure” policy evaluates whether the price reaction is failing despite the surprise. That policy requires stronger proof: price must reclaim the pre-release range and yields must stop extending.

The conditions are not yet met.

Decision: `NO_TRADE — FUNDAMENTAL_CONFLICT`.

## 6. Later development

Price fails to reclaim the pre-release range and resumes lower. The rejected trade would have stopped.

This rejection is retained as research evidence that the conflict gate prevented a loss.

## 7. Alternate outcome

Had price reclaimed the full pre-release range, futures delta turned positive, yields retraced, and the first pullback held, the candidate could have become:

```text
direction: LONG
entry: first pullback after reclaim
stop: below sweep extreme plus buffer
target_1: pre-release high-volume node
target_2: prior-day high if structure remains healthy
risk: reduced counter-news allocation
max_duration: setup-specific
```

The risk and execution services would still need to approve it.

## 8. Trace payload

The stored trace links:

- calendar release event;
- consensus snapshot;
- yield data;
- broker quotes;
- futures trades/delta;
- zone and liquidity IDs;
- structure events;
- policy version;
- risk snapshot;
- final rejection;
- hypothetical outcome for research.

The narrative is generated from these fields after the decision.
