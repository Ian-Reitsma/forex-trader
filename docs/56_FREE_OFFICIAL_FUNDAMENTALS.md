# v0.7.36 Free Official/Public Fundamentals

## Goal

OANDA Practice campaigns must satisfy the existing fundamentals requirement without a paid economic-calendar or market-consensus subscription.

This implementation does **not** manufacture economist consensus from public data and does not relabel official actual data as a forecast surprise. It uses a separate point-in-time `indicator` observation whose meaning is:

> What does the latest authoritative public policy/inflation state say, and how did the published value change versus the previous comparable value when that comparison is available?

The existing `release` observation remains the correct representation for actual-versus-consensus surprise data when legitimate point-in-time consensus evidence exists.

## No-key source map

The runtime uses public HTTPS endpoints and sends no provider API credential.

| Currency | Policy source | Inflation source |
| --- | --- | --- |
| USD | Federal Reserve FOMC statements | BLS Public Data API, CPI-U index (`CUUR0000SA0`) |
| EUR | ECB Data Portal key rates | ECB Data Portal HICP API |
| GBP | Bank of England Bank Rate history | Office for National Statistics CPI bulletin |
| JPY | BIS central-bank policy-rate series (`M.JP`) | BIS consumer-price year-over-year series (`M.JP.771`) |
| CHF | Swiss National Bank monetary-policy assessment | Swiss National Bank monetary-policy assessment |
| CAD | Bank of Canada key monetary-policy variables | Bank of Canada key monetary-policy variables |
| AUD | Reserve Bank of Australia cash-rate history | Reserve Bank of Australia CPI page (ABS source data) |
| NZD | BIS central-bank policy-rate series (`M.NZ`) | Stats NZ quarterly CPI release |

The BIS policy-rate series are constructed in collaboration with national central banks and the daily observations are reported directly by member central banks. The BIS CPI data set is predominantly sourced from national statistical offices. Exact public response bodies are retained as source evidence before deterministic indicator observations are created.

No Trading Economics credential is required by `run_practice_campaign.py` or `sync_free_official.py`.

## Source-resilience changes

Live no-key testing exposed HTTP/application and page-layout failures rather than trading-engine failures. The resilient paths now avoid those brittle surfaces:

- **USD/BLS:** the runtime does not scrape the BLS CPI release HTML page. It uses the unregistered/no-key BLS Public Data API v1, retrieves CPI-U index history, and calculates current/previous 12-month changes.
- **JPY:** deployable JPY policy and inflation use machine-readable BIS Statistics API series rather than guessed BoJ publication URLs or Statistics Japan HTML encoding/layout.
- **NZD:** automated RBNZ access is absent. Policy uses the BIS machine-readable policy-rate series. Inflation uses Stats NZ first-party quarterly CPI releases. The adapter constructs predictable quarterly release slugs newest-first and skips a candidate only on HTTP 404, so transport/server/parser failures cannot silently select stale data.

No commercial consensus feed, synthetic consensus, or unofficial market-calendar mirror is used.

## Point-in-time policy

The free runtime is prospective-first-seen:

1. A source is fetched from an approved public HTTPS host.
2. The exact raw body is stored as evidence.
3. The latest policy/inflation state is parsed.
4. An immutable deterministic `MacroObservationKind.INDICATOR` is written only if that exact source/reference/value tuple has not already been seen.
5. `available_at` is the local retrieval time, so a value discovered today cannot appear in a historical decision yesterday.
6. No forecast field is allowed on an indicator observation.

Historical backtests that need true release-time state still require a historical point-in-time dataset. The prospective runtime intentionally does not backdate current public values into old decisions.

## Confidence versus directional alpha

The fundamental model separates evidence coverage from directional freshness.

- **Directional score freshness:** policy 21 days, inflation/growth 72 hours, labor 48 hours, news 6 hours.
- **Evidence coverage confidence:** policy 365 days, inflation/growth 180 days, labor 90 days, news 6 hours.
- The existing 30-day maximum age still hard-expires non-policy components by default.

This means a CPI trend stops exerting strong directional force after a few days while the model can still know that inflation is covered by a current authoritative publication.

The strategy component weights remain unchanged:

- policy: 0.35
- inflation: 0.20
- growth: 0.15
- labor: 0.15
- news: 0.15

Current policy + inflation coverage therefore represents 0.55 of the total evidence model and can satisfy the existing minimum fundamental confidence of 0.50 when both sides of a pair are current. Policy alone cannot satisfy the gate.

No minimum score, spread, slippage, confirmation, risk, drawdown, correlation, macro-factor, reconciliation, or broker-write threshold is lowered.

## Health semantics and failure behavior

Source failures remain isolated by currency. A temporary failure at one publisher does not contaminate other currencies with a commercial source or synthetic value.

Provider-level health has three explicit states:

- `healthy`: every attempted currency succeeded;
- `degraded`: at least one attempted currency succeeded and at least one failed;
- `unavailable`: no attempted currency succeeded.

The JSON compatibility field `healthy` is `true` only for full success. A partial source refresh therefore reports `status: degraded` and `healthy: false` rather than presenting itself as healthy.

The sync report records currencies attempted/succeeded, raw payloads, indicators, observations, component counts, per-currency failures, `status`, and `healthy`.

## Commands

Standalone provider diagnostic:

```bash
python scripts/sync_free_official.py
```

Shadow eligibility diagnostic:

```bash
python scripts/run_practice_campaign.py \
  --all-currency-pairs \
  --eligible-only \
  --max-cycles 1 \
  --decision-evidence-path campaign-decisions.jsonl
```

OANDA Practice campaign:

```bash
forex-trader sync

python scripts/run_practice_campaign.py \
  --execute \
  --all-currency-pairs \
  --max-orders-per-cycle 1 \
  --max-cycles 12 \
  --decision-evidence-path campaign-decisions.jsonl
```

Both `--eligible-only` and `--execute` automatically run the free fundamentals refresh before building the strategy engine and fundamental universe preflight.

A successful fundamentals refresh does not guarantee a trade. Technical structure, liquidity, spread, execution cost, portfolio risk, reconciliation and all other existing gates remain authoritative.
