# 16 — Implementation Status

## Current release

Version 0.7.30 is the current Practice-only FX research/execution platform. It retains the audited runtime/risk/telemetry/replay architecture through v0.7.29 and adds a reproducible staged historical-development harness plus Jan-Mar 2026 evidence. The system remains intentionally paper/Practice-only.

OANDA is restricted to fxTrade Practice endpoints. `sweep_reclaim:v1` remains the only Practice-authorized strategy family. No v0.7.30 historical research output, structured-zone threshold, macro/flow diagnostic, model output, telemetry output, or LLM output can directly authorize or submit orders.

## Runtime authority boundary

The machine-readable authority contract remains `config/system-policy-v0.7.json`.

- Real-money execution is disabled.
- Broker writes require paper/Practice mode, explicit write enablement, and reconciliation readiness.
- Unknown/ambiguous execution state halts new risk until reconciled.
- `sweep_reclaim:v1` remains the only Practice-authorized strategy family.
- Broker tick activity cannot satisfy institutional-flow confirmation.
- Research-only structured zones, flow-divergence/VWAP policies, annotation outputs, and historical diagnostics have no execution authority.

## Historical research fidelity

The historical research stack now supports:

- first-party Dukascopy BI5 best-bid/best-ask ticks with local cache and resilient acquisition;
- M5/H1 causal feature bars derived from the same tick archive;
- exact tick-path stop/target ordering, observed spread, explicit entry latency and adverse slippage;
- full-period return reporting with canonical 5 p.m. New York FX-risk-day metrics as the primary research day basis;
- production `EnhancedRiskPolicy` replay with causal account state, open positions, reserved risk, currency/gross exposure, macro-factor concentration, drawdown/loss streak, and point-in-time H1 correlation history;
- research-only RBR/RBD/DBR/DBD structured-zone evidence;
- causal assembly of genuinely pre-release consensus snapshots with actual releases when such an archive is supplied;
- centralized-flow feature decomposition when an eligible futures/order-flow archive is supplied;
- fail-closed external-data behavior: missing PIT consensus or centralized flow remains unavailable rather than being replaced by retrospective consensus or broker tick proxies.

## v0.7.30 Jan-Mar development evidence

A new development tape, 2026-01-05 through 2026-03-31, was opened after the earlier April-May sealed-validation failure. The prior May-August development tape and April-May sealed tape were not used to set the original Jan-Mar staged thresholds. No new untouched validation window was opened.

The predeclared exact-tick run generated 1,935 causal opportunities and 633 same-instrument non-overlapping legacy executions across EUR/USD, GBP/USD and USD/JPY. The broad legacy technical baseline was negative: 633 trades, -0.09590R expectancy, profit factor 0.8065, -60.705R total and 63.026R maximum drawdown. At fixed 0.15% risk per selected trade the preserved run compounded to -8.7754%.

The original structured-zone gate required quality >=0.50 and distance <=0.50 ATR and selected 0/633 shared executions. An outcome-blind follow-up established that the detector itself had high coverage: 1,738/1,935 raw causal decisions had a same-direction unbroken structured zone, while only 14 were within 0.50 ATR. The proximity threshold, not detector availability, was the binding issue.

After Jan-Mar outcomes were already open, a small development-only grid showed positive neighboring results only for the high-quality tail. A development hypothesis was frozen at quality >=0.75 and distance <=5 ATR. It produced 39 trades at +0.04875R expectancy and PF 1.139, but its one-sided 95% expectancy lower bound was -0.17954R. GBP/USD was negative, February and March were negative, and every pair/month subgroup retained a negative uncertainty lower bound. The candidate is therefore development-selected and unproven, not promotion-ready.

Production risk admitted 34/39 of that selected subset and ended the synthetic $100k account at $100,138.07 (+0.1381%) with 0.4587% maximum equity drawdown. Risk controls reduced/limited exposure; they do not establish strategy edge.

See `docs/54_V0_7_30_STAGED_HISTORICAL_DEVELOPMENT.md` and `config/audit-traceability-v0.7.30.json` for exact workflow/artifact provenance.

## External data still required

The requested full staged architecture is not yet historically measured. The repository does not contain:

- a qualifying historical point-in-time economic consensus archive with pre-release snapshots and release actuals for the Jan-Mar development period;
- an eligible centralized FX futures/order-flow archive with frozen contract selection, roll boundaries, pair orientation/scale mapping and source quality controls.

The runner already accepts normalized archives for both components and fails closed when they are absent. Dukascopy/broker tick activity is not treated as centralized institutional flow.

The next valid experiment is therefore not another technical optimization. Supply those two qualifying archives, run PIT macro and centralized-flow attribution on the same already-open Jan-Mar development tape with the structured subpolicy fixed, replay the complete chain through production risk, and freeze the resulting complete policy. Only then may one completely untouched historical window be opened once.

## Evidence integrity

The repository continues to enforce these distinctions:

- candidate quality is not a win probability;
- future observations are excluded from point-in-time decisions;
- decision evidence and future outcome evidence are separate;
- post-outcome Jan-Mar diagnostics are labeled development-only and cannot be represented as validation;
- campaign fingerprints change with outcome-affecting software/policy identity;
- promotion requires after-cost expectancy, drawdown, uncertainty-aware evidence, sample sufficiency, cross-pair/regime stability, replay reproducibility, and sustained Practice evidence;
- passing software CI does not establish profitability.

## Validation and operations

Standard CI continues to run compilation, dependency integrity, secret scanning, critical Ruff, strict typing, full pytest with branch-aware coverage, and protected-paper smoke across supported Python versions. Audit/risk, operations, replay, annotation-integrity, and historical-backtest gates remain active.

Heavy Jan-Mar evidence workflows are manual-only after evidence capture so ordinary source/documentation commits do not repeatedly consume the historical archive or create accidental additional outcome runs.

## OANDA Practice evidence

Historical profitability is not sufficient to bypass broker evidence. The future open-market sequence remains: authenticated read-only Practice validation, reconciliation, all-pair shadow campaign, separately gated broker-minimum protected open/verify/close round trip, then a capped sustained Practice campaign with mature outcome/after-cost attribution.
