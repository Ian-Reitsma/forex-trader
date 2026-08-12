# v0.7.41 Risk Correctness and Breaker Recovery

## Scope

v0.7.41 is a runtime/risk correctness release for the OANDA Practice autonomous trader. It does not relax the strategy score, spread, slippage, structure, sweep/retest, reward-to-risk, portfolio exposure, correlation, macro-factor exposure, or position-count gates. It does not add live-money authority.

The release responds to forward evidence gathered through August 12, 2026: six genuine strategy trades had closed as losses, while the advanced loss-streak state reported seven observations because the historical one-unit capability probe was also being counted. The six genuine losses remain authoritative strategy evidence.

## Strategy-owned realized outcome reconciliation

Advanced risk no longer consumes every nonzero OANDA `ORDER_FILL.pl` value. Broker reconciliation now reconstructs strategy ownership from the same durable lineage used by promotion accounting:

1. a strategy entry order must have a `clientExtensions.id` beginning with `ft-` and the `forex-trader` tag;
2. its OANDA opening fill establishes the owned trade ID;
3. a later dependent stop/take-profit/close fill belongs to the strategy only when its `tradesClosed.tradeID` belongs to that owned trade lineage;
4. probe and manual broker activity do not mutate the strategy loss streak;
5. financing remains part of strategy economics but is not a separate win/loss observation.

The trailing strategy loss streak is rebuilt deterministically from durable owned history on each reconciliation. This repairs databases whose pre-v0.7.41 advanced-risk row was contaminated by non-strategy fills while preserving broker history and promotion evidence.

## Loss-streak breaker recovery

Six consecutive genuine strategy losses still trip the configured breaker at `max_loss_streak=6`. The breaker remains fail-closed; v0.7.41 does not automatically resume after a timer and does not raise the limit.

Recovery requires an explicit operator review while the autonomous daemon is stopped and there are no open broker positions. `scripts/review_loss_breaker.py` performs a fresh broker reconciliation, verifies the durable autonomous lease is not owned, verifies there are no open positions, binds the review to the exact reconciled OANDA transaction cursor, creates a unique durable audit record, establishes a new consecutive-loss observation epoch, reconciles again, and prints the before/review/after state.

The review changes only the active loss-streak observation epoch. It does not remove the prior six losses from OANDA history, decision evidence, promotion statistics, or research datasets.

Read-only status is available with:

```bash
python scripts/risk_status.py
```

A reviewed Practice-only recovery is explicit:

```bash
python scripts/review_loss_breaker.py \
  --confirm-practice-resume \
  --reason "Operator reviewed the six strategy-owned Practice losses and authorizes a new unchanged-risk observation epoch."
```

## Macro-factor execution coverage

The default macro-factor taxonomy now covers all 28 unique currency pairs formed by the free-official eight-currency universe: AUD, CAD, CHF, EUR, GBP, JPY, NZD, and USD. Every pair receives macro and rates concentration tags for both currency legs; pairs containing AUD, CAD, or NZD also receive the existing `commodity_cycle` concentration tag.

`require_classification=true` remains fail-closed. This fixes the previous inconsistency where a pair could pass fundamental coverage yet be structurally incapable of authorization only because the default factor policy had no entry for that pair.

## Deliberately not promoted in this release

The observed 34-hour USD/CHF M5 position and rollover stop-spread expansion are serious trading-system findings, but position-management write authority is not enabled by this release. The existing runtime management policy must first be run as shadow/counterfactual evidence against actual and historical positions before any automatic time-stop, pre-rollover flatting, break-even move, or event-driven management can write to OANDA Practice.

Likewise, v0.7.41 does not raise the 2.0-pip entry spread ceiling, increase risk or maximum units, lower the score threshold, weaken portfolio/correlation vetoes, or claim improved profitability. The next trading research step remains outcome labeling of matured candidates and near-miss cohorts across preregistered horizons.
