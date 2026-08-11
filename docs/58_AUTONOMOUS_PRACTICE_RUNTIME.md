# Autonomous OANDA Practice Runtime

`forex-trader serve` is intentionally observational. It serves the authenticated API and UI but does not evaluate markets.

The canonical continuous Practice process is:

```bash
forex-trader autonomous --max-orders-per-cycle 1
```

Omit `--max-cycles` to run continuously. The runtime defaults to one configured lower-timeframe bar between cycles, discovers the broker currency universe, prefilters pairs that cannot satisfy the configured point-in-time fundamental confidence requirement, and never relaxes strategy or risk gates to manufacture fills.

Each cycle is fail-closed around broker state: it catches up the durable OANDA transaction cursor before evaluation, refreshes free first-party official fundamentals on cadence, reloads the point-in-time fundamental book, refreshes broker discovery on cadence, evaluates the eligible universe with the existing Practice-authorized strategy/risk policy, and catches up broker transactions again after the cycle. Unresolved broker writes stop further risk.

A durable SQLite singleton lease prevents two autonomous runners from owning execution at once, and an owner token fences broker writes if a stalled process loses that lease. A durable `autonomous_practice` heartbeat is stored in SQLite. `/v1/runtime` and `/v1/status.runtime` report whether the trading process is active, its campaign/cycle, eligible/discovered counts, broker cursor, last fundamental refresh, errors, heartbeat age and staleness. API liveness is not trading liveness.

`forex-trader run --execute` also uses the durable OANDA runtime and defaults to broker discovery plus fundamental eligibility filtering. Pass `--configured-pairs` only when you intentionally want to restrict execution to `FOREX_INSTRUMENTS`. Non-OANDA/shadow `run` retains the generic polling loop.

Promotion accounting accepts only strategy client IDs with the `ft-` prefix plus the `forex-trader` tag. Explicit `probe-` round trips are excluded. OANDA `DAILY_FINANCING` rows are attributed to owned open trade IDs and included in the strategy trade's realized economics.

A final `protected` lifecycle state counts as both a broker fill and verified protection in campaign aggregates. Execution also rechecks runtime data-quality readiness at the write boundary before submitting Practice risk.
