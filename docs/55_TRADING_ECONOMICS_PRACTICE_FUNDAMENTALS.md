# Trading Economics Prospective Practice Fundamentals

## Purpose

This integration supplies the OANDA Practice execution path with legitimate current macro-calendar observations instead of demo seeds. It does not change the strategy score, the minimum fundamental-confidence gate, risk limits, reconciliation requirements, or broker-write authority.

The feed is intentionally classified as `LICENSED`. Trading Economics may expose publisher/source metadata for an event, but a response retrieved from the Trading Economics API is not relabeled as a first-party central-bank or government payload. The existing `MacroIngestionOrchestrator` contract for licensed consensus plus independently fetched `OFFICIAL` actual evidence remains unchanged and remains the stronger research-grade path.

## Runtime flow

When `TRADING_ECONOMICS_API_KEY` is present and `TRADING_ECONOMICS_AUTO_REFRESH=true`, `scripts/run_practice_campaign.py --execute` performs a licensed macro refresh before building the strategy engine and before fundamental universe preflight:

1. Request recent economic-calendar windows from `https://api.tradingeconomics.com` for the configured country set.
2. Request JSON with `values=true` so numeric actual/forecast/previous fields are available where the API supplies them.
3. Persist each raw response in `macro_source_payloads` as `SourceAuthority.LICENSED`.
4. Parse supported released macro events for mapped currencies.
5. Require actual, forecast, previous, recognized event semantics, and configured minimum importance.
6. Append immutable `MacroObservation.release` rows to the same SQLite database used by the trading engine.
7. Rebuild the engine from the now-populated point-in-time observation ledger.
8. Run the unchanged fundamental-confidence preflight.
9. Only pairs that pass fundamentals continue to technical, risk, reconciliation, and broker execution gates.

The standalone equivalent is:

```bash
python scripts/sync_trading_economics.py
```

## Credential handling

The only secret is `TRADING_ECONOMICS_API_KEY`. It must remain in local `.env` or another external secret store and must never be committed.

The default authentication mode is `header`, which sends the API credential directly in the HTTP Authorization header:

```text
Authorization: <credential>
```

`TRADING_ECONOMICS_AUTH_MODE=query` exists for vendor-plan compatibility and sends the credential using the documented `c` query parameter. When query authentication is used, persisted provenance URLs strip `c`/`client` credential parameters and raised API errors redact the configured credential.

The base URL is fail-closed to `https://api.tradingeconomics.com`. Redirects are not followed. A response outside the approved host, an oversized payload, malformed JSON, HTTP failure, or throttle/rate-limit response aborts a Practice execution refresh before any strategy order can be submitted.

## Point-in-time policy

This runtime integration is **prospective-first-seen** and deliberately separates two clocks:

- `available_at` is the timestamp when the local runtime first retrieved the event. It controls **knowability**: a current API response cannot become visible to an earlier decision or backtest timestamp.
- `event_at` is the original UTC economic-release timestamp from the calendar. It controls **freshness/decay**: retrieving a six-day-old release today does not make that release appear six seconds old to the fundamental model.

A current Trading Economics response can contain an event that happened days earlier and may already contain revised values. The importer therefore does not backdate `available_at` to the historical release timestamp. The vendor event ID is used as an immutable first-seen identity, so later refreshes of the same event do not duplicate or rewrite the observation.

This is deliberately conservative. It prevents current/revised vendor data from leaking into an earlier historical decision timestamp while preserving the real age of the economic information. Historical research requiring true as-of consensus/actual evidence should continue to use the repository's dedicated point-in-time historical source paths rather than this prospective runtime feed.

## Event coverage

The adapter recognizes macro events in four components already understood by `FundamentalBook`:

- `policy`: interest-rate decisions, policy/bank/cash rates, monetary-policy decisions;
- `inflation`: CPI, PCE prices, PPI, consumer/producer price and inflation releases;
- `labor`: unemployment, employment/payrolls, jobless claims, wages/earnings and labor-market releases;
- `growth`: GDP, PMI, retail sales, industrial/manufacturing production, confidence, trade/current-account and major activity/housing releases.

Higher unemployment/jobless/inflation observations are directionally negative under the existing scalar release model. Higher policy rates and standard growth/activity releases are directionally positive. This remains a simplified strategy feature, not a claim that every macro surprise has a universal monotonic FX effect.

Importance is normalized from the vendor's 1-3 scale to 0.50 / 0.75 / 1.00. The default `TRADING_ECONOMICS_MIN_IMPORTANCE=2` excludes low-importance releases.

The default country set covers the eight major currencies used by the existing fundamental engine plus common additional OANDA FX economies. The endpoint uses the API's documented multi-country calendar/date-range form rather than relying on an undocumented `All` country alias. The downstream strategy still owns eligibility. Missing fundamental confidence, missing macro-factor classification, correlation constraints, spread, technical structure, risk, or execution readiness can all independently veto a trade.

## Environment

```dotenv
TRADING_ECONOMICS_API_KEY=
TRADING_ECONOMICS_BASE_URL=https://api.tradingeconomics.com
TRADING_ECONOMICS_TIMEOUT_SECONDS=15
TRADING_ECONOMICS_HISTORY_DAYS=30
TRADING_ECONOMICS_WINDOW_DAYS=7
TRADING_ECONOMICS_MIN_IMPORTANCE=2
TRADING_ECONOMICS_AUTO_REFRESH=true
TRADING_ECONOMICS_AUTH_MODE=header
TRADING_ECONOMICS_MAX_PAYLOAD_BYTES=8000000
TRADING_ECONOMICS_COUNTRIES=United States,Euro Area,United Kingdom,Japan,Switzerland,Canada,Australia,New Zealand,China,Czech Republic,Denmark,Hong Kong,Hungary,Mexico,Norway,Poland,Singapore,South Africa,Sweden,Turkey
```

`TRADING_ECONOMICS_HISTORY_DAYS` is bounded to 1-90 and window size to 1-31. These are acquisition bounds only; the existing `FundamentalBook` half-life/freshness decay still determines how much confidence an observation contributes at decision time.

## Practice execution

After OANDA read access and reconciliation are established:

```bash
python scripts/sync_trading_economics.py

python scripts/run_practice_campaign.py \
  --execute \
  --all-currency-pairs \
  --max-orders-per-cycle 1 \
  --max-cycles 12 \
  --decision-evidence-path campaign-decisions.jsonl
```

The first command is optional when automatic refresh is enabled; it is useful as an explicit data-provider diagnostic. The execute command will refresh again, report the licensed refresh summary, perform fundamental preflight, and only then allow the existing strategy/risk stack to authorize OANDA Practice orders.

A successful data refresh does not guarantee a trade. Trade frequency remains an outcome of the unchanged gates.
