# v0.7.33 Free Official Fundamentals

## Goal

OANDA Practice campaigns must be able to satisfy the existing fundamentals requirement without a paid economic-calendar or market-consensus subscription.

This implementation does **not** manufacture economist consensus from public data and does not relabel official actual data as a forecast surprise. It adds a separate point-in-time `indicator` observation whose meaning is:

> What does the latest first-party official policy/inflation state say, and how did the published value change versus the previous comparable official value when that comparison is available?

The existing `release` observation remains the correct representation for actual-versus-consensus surprise data when legitimate point-in-time consensus evidence exists.

## No-key source map

The runtime uses only first-party/public HTTPS endpoints and sends no provider API credential.

| Currency | Policy source | Inflation source |
| --- | --- | --- |
| USD | Federal Reserve FOMC statements | U.S. Bureau of Labor Statistics CPI tables |
| EUR | ECB Data Portal key rates | ECB Data Portal HICP API |
| GBP | Bank of England Bank Rate history | Office for National Statistics CPI bulletin |
| JPY | Bank of Japan monetary-policy decisions | Statistics Bureau of Japan CPI indicator |
| CHF | Swiss National Bank monetary-policy assessment | Swiss National Bank monetary-policy assessment |
| CAD | Bank of Canada key monetary-policy variables | Bank of Canada key monetary-policy variables |
| AUD | Reserve Bank of Australia cash-rate history | Reserve Bank of Australia CPI page (ABS source data) |
| NZD | Reserve Bank of New Zealand OCR page | Reserve Bank of New Zealand Prices M1 (Stats NZ source data) |

No Trading Economics credential is required by `run_practice_campaign.py` or `sync_free_official.py`.

## Point-in-time policy

The free runtime is prospective-first-seen:

1. A source is fetched from an approved first-party HTTPS host.
2. The exact raw body is stored as `SourceAuthority.OFFICIAL` evidence.
3. The latest policy/inflation state is parsed.
4. An immutable deterministic `MacroObservationKind.INDICATOR` is written only if that exact source/reference/value tuple has not already been seen.
5. `available_at` is the local retrieval time, so a value discovered today cannot appear in a historical decision yesterday.
6. No forecast field is allowed on an indicator observation.

Historical backtests that need true release-time state still require a historical point-in-time dataset. The prospective runtime intentionally does not backdate current webpages into old decisions.

## Confidence versus directional alpha

The old fundamental model used one freshness concept for both direction and confidence. That is appropriate for short-lived surprise/news impulses but not for monthly or quarterly first-party macro publications.

v0.7.33 separates them:

- **Directional score freshness** keeps the existing short half-lives: policy 21 days, inflation/growth 72 hours, labor 48 hours, news 6 hours.
- **Evidence coverage confidence** decays much more slowly across the normal publication cycle: policy 365 days, inflation/growth 180 days, labor 90 days, news 6 hours.
- The existing 30-day maximum age still hard-expires non-policy components by default.

This means a CPI trend can stop exerting strong directional force after a few days while the model can still know that inflation is covered by a current authoritative publication.

The strategy's existing component weights are unchanged:

- policy: 0.35
- inflation: 0.20
- growth: 0.15
- labor: 0.15
- news: 0.15

Current first-party policy + inflation coverage therefore represents 0.55 of the total evidence model and can satisfy the existing minimum fundamental confidence of 0.50 when both sides of a pair are current. Policy alone cannot satisfy the gate.

No minimum score, spread, slippage, confirmation, risk, drawdown, correlation, macro-factor, reconciliation, or broker-write threshold is lowered.

## Failure behavior

Source failures are isolated by currency. A temporary failure at one publisher does not contaminate other currencies with a fallback commercial source or synthetic value.

Example: if the Statistics Bureau of Japan page changes and JPY cannot be parsed, JPY is reported as unavailable. EUR/USD may remain eligible if EUR and USD have sufficient official evidence. JPY pairs fail the normal fundamental preflight.

The sync report records:

- currencies attempted and succeeded;
- raw official payloads inserted;
- indicators seen;
- observations inserted/already existing;
- policy/inflation component counts;
- per-currency failures;
- provider health.

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

Both `--eligible-only` and `--execute` automatically run the free official refresh before building the strategy engine and fundamental universe preflight.

A successful fundamentals refresh does not guarantee a trade. Technical structure, liquidity, spread, execution cost, portfolio risk, reconciliation and all other existing gates remain authoritative.
