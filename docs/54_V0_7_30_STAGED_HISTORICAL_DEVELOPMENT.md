# v0.7.30 Staged Historical Development

Date: 2026-08-09

## Scope and evidence boundary

This release records the next development campaign after the v0.7.29 April-May sealed-validation failure. The new development tape is 2026-01-05 through 2026-03-31, with 2025-12-22 through 2026-01-04 used only for causal price warmup. The prior May-August development tape and April-May sealed tape were not used to choose the original staged thresholds. No new untouched validation window was opened by this release.

The intended sequence was evaluated on one shared causal execution stream: legacy technical baseline, structured-zone evidence, genuine point-in-time macro surprise, genuine centralized flow, then production portfolio-risk replay. Historical executions use first-party Dukascopy BI5 best bid/ask ticks, M5/H1 midpoint feature bars derived from those ticks, 500 ms entry latency, 0.10 pip adverse slippage on each side, and a 120-minute maximum holding period.

## Predeclared Jan-Mar result

The exact completed outcome-bearing run was GitHub Actions run `31331626246` at head `ac4d3e552455986e0f3c3dc05a694587957f2ad0`. Evidence artifact `staged-historical-development-v1` has SHA-256 `1f0b4d0c37e5542a3a3eb68f281cdee54541016e0a5ec3284bc12a791145d964`.

The history including warmup contained 5,850,367 EUR/USD ticks, 7,152,660 GBP/USD ticks, and 7,471,078 USD/JPY ticks. Generation produced 1,935 causal executions and 633 same-instrument non-overlapping legacy executions.

The legacy technical baseline was negative after executable costs: 633 trades, 120 target wins, 265 stop losses, 248 timeouts, 18.96% target-hit win rate, -0.09590R expectancy per trade, profit factor 0.8065, -60.705R total, and 63.026R maximum drawdown. At fixed 0.15% risk per selected trade, the preserved v1 artifact compounded to -8.7754% over the declared period. The baseline was negative across all three pairs and all three calendar months; the strongest attribution distinction was direction, with shorts approximately break-even and longs materially negative. That observation is attribution only and is not used to launch another short-only optimization pass in this release.

The predeclared structured-zone gate required an aligned unbroken RBR/RBD/DBR/DBD zone with research quality at least 0.50 and entry within 0.50 ATR. It selected 0 of the 633 shared executions. The run did not loosen that threshold after seeing outcomes.

The genuine PIT macro-surprise stage was unavailable because no normalized historical archive containing truly pre-release consensus snapshots plus actual releases was supplied. The genuine centralized-flow stage was unavailable because no eligible centralized futures/order-flow archive was supplied. Broker/Dukascopy tick activity was not substituted for institutional flow. Therefore the complete structured-zone -> PIT macro -> centralized-flow chain was not measured.

## Production-risk diagnostic

Because the predeclared structured gate selected zero and the macro/flow stages were unavailable, the v1 artifact explicitly labels the production-risk input as `legacy_technical`. That replay is a safety diagnostic on the deepest usable stream, not the requested final sequential pipeline.

The production `EnhancedRiskPolicy`, with causal account/open-position state and H1 correlation history, admitted 15 of 633 legacy opportunities and denied 618. The six-loss observation limit accounted for 575 later denials. The synthetic account moved from $100,000 to $99,287.48, a -0.7125% result and 0.7125% maximum equity drawdown. The admitted subset remained negative. The risk layer therefore reduced capital damage; it did not manufacture edge.

## Outcome-blind structured-zone diagnosis

After the 0/633 result, an outcome-blind scanner measured structured-zone availability without walking the future trade path. Run `31335644029` produced artifact `structured-zone-coverage-v1`, SHA-256 `89db850e322ce2f436791ad6cc522976670de2daeaa17e6d45c997c47fa7d945`.

On the 1,935 raw causal decisions, a same-direction unbroken structured zone existed for 1,738 decisions (89.82%). A total of 1,202 cleared quality 0.50, while only 14 were within 0.50 ATR and only nine cleared both predeclared conditions before non-overlap ownership. Median nearest-zone distance was approximately 2.91 ATR. The detector therefore had substantial causal coverage; the binding issue was the overly restrictive predeclared distance gate, not a broken detector.

## Explicitly post-outcome structured-zone development

The Jan-Mar tape was already open at this point. All following threshold work is development-selected and must never be represented as predeclared or validation evidence.

Run `31335644034`, artifact `structured-zone-development-diagnostics-v1`, SHA-256 `ee63bd077e560673ab736a8f6c19d6bbd7efb502147400e5248f958bb713a827`, evaluated a small quality/distance grid on the same 633 shared executions. Every quality threshold at or below 0.50 remained negative. The only positive neighboring row was quality at least 0.75: maximum distance 3 ATR produced 20 trades at +0.2181R expectancy/PF 1.80, 5 ATR produced 39 trades at +0.04875R/PF 1.139, and 10 ATR produced 52 trades at +0.08332R/PF 1.208.

The development subpolicy was frozen at quality >=0.75 and distance <=5 ATR because it is the middle of the positive 3/5/10-ATR neighborhood, carries more sample than the sharp 3-ATR cell, and avoids choosing the semantically loosest 10-ATR endpoint. This selection occurred after outcomes were open.

A final attribution/risk run `31336654237` at head `941b55bcdce2fa54b8f3152aaabde1a4ac9cb549` produced artifact `structured-zone-development-diagnostics-v1` with schema `structured-zone-development-diagnostics-v2` and SHA-256 `176f2f46c7e624c5637e78f288eaa7b79172eeb7c1cd4629fb130f72beefdfb7`.

The selected 0.75/5-ATR candidate remains unproven: 39 trades, 7 target wins, 10 stop losses, 22 timeouts, +0.04875R expectancy, PF 1.139, +1.901R total, and 4.199R maximum drawdown. Its normal-approximation one-sided 95% expectancy lower bound is -0.17954R, so uncertainty still includes a materially negative edge. At fixed 0.15% risk per selected trade it compounded to +0.28234%; the canonical 5 p.m. New York FX-risk-day average across all 63 risk days was approximately +0.00452% per risk day.

The pooled positive result is not stable enough for promotion. EUR/USD was positive (+0.1927R across 12 trades), GBP/USD negative (-0.2607R across six), and USD/JPY slightly positive (+0.0549R across 21). January was positive (+0.3129R across 15), February negative (-0.0386R across 12), and March negative (-0.1941R across 12). Every pair and month subgroup had a negative one-sided 95% expectancy lower bound. Longs were effectively flat while shorts were modestly positive, but both direction-specific lower bounds were negative. No further technical parameter search is performed in v0.7.30.

Production risk admitted 34 of the 39 selected-zone candidates and denied five for holiday/correlation constraints. The synthetic account ended at $100,138.07 (+0.1381%) with 0.4587% maximum equity drawdown. This is useful safety evidence, but it does not convert the development-selected technical candidate into a validated strategy.

## Decision

The broad legacy technical stream is rejected as a positive-edge candidate on this development tape. The structured-zone detector is retained as research infrastructure. The quality >=0.75 / distance <=5 ATR configuration is frozen only as an unproven development hypothesis for the eventual full-data staged policy; it is not promoted to Practice authority and is not eligible to justify opening a new validation window by itself.

The next legitimate experiment is data-dependent: supply a genuinely point-in-time historical consensus/actual archive and an eligible centralized futures/order-flow archive, run those components on this same already-open Jan-Mar development tape with the technical subpolicy fixed, replay the resulting chain through production risk, and then freeze the complete policy. Only after that complete policy is fixed may one completely untouched historical window be opened once.

## Authority

No runtime strategy authority changes in v0.7.30. OANDA remains Practice-only. `sweep_reclaim:v1` remains the only Practice-authorized strategy family. Structured-zone research outputs, macro/flow research outputs, and historical diagnostics cannot directly authorize or submit orders.
