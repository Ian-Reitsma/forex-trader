# 50 — v0.7.24 Macro-Factor Risk and Technical Validation

## Purpose

v0.7.24 closes three software gaps from the post-v0.7.22 audit while preserving the Practice-only authority boundary:

1. explicit macro-factor/event-thesis concentration risk independent of rolling return correlation;
2. blinded technical chart human-ground-truth infrastructure for zones, sweeps, structure shifts, retests, and direction;
3. concrete research-only flow-divergence and centralized-VWAP repositioning state machines.

None of these changes grants live-money authority. `sweep_reclaim:v1` remains the only Practice-authorized setup family.

## 1. Macro-factor concentration

Return correlation is useful but insufficient for event-driven FX risk. Two pairs can temporarily decorrelate while both remain exposed to the same central-bank or macro repricing. `MacroFactorClusterGuard` therefore applies an independent gross-notional limit to explicit policy clusters.

The v1 taxonomy is stored in `config/macro-factor-clusters-v1.json` and is embedded in code as the default runtime policy. The initial universe is tagged by currency macro/rates factors, with commodity-cycle tags for AUD/CAD/NZD pairs where relevant.

The guard prices every existing position and the proposed position in account currency, sums gross notional into every declared factor, and denies the authorization when the largest factor exceeds the configured capital-relative ceiling. Under strict classification it also denies unclassified instruments and positions that cannot be priced safely.

This is a separate veto from:

- per-trade stop risk;
- daily marked-loss limits;
- gross currency-leg exposure;
- per-currency concentration;
- margin reserve;
- signed return correlation;
- trailing drawdown;
- loss streak;
- reserved/pending risk;
- gap-stressed maximum loss.

The default factor ceiling is `2.5 ×` account capital. That number is a conservative initial policy value, not an optimized result. Real replay and Practice evidence must determine whether the taxonomy or ceiling should change.

## 2. Campaign cohort integrity

Because the risk decision changes in v0.7.24, the campaign identity contract changes as well. `campaign-policy-v2` fingerprints:

- the macro-factor ceiling;
- strict-classification mode;
- the complete sorted instrument-to-factor taxonomy;
- trailing drawdown limit;
- loss-streak limit;
- reserved-risk limit;
- gap-stress multiplier;
- the risk-policy semantic version.

A campaign with a different factor map or risk limit therefore cannot silently share an evidence cohort with an older policy.

## 3. Blinded technical annotation

The technical validation workflow is deliberately designed to avoid self-validation.

Reviewer packets contain raw completed OHLCV windows and deterministic hashes only. They exclude model detections, model scores, selected policies, candidates, stops, targets, execution decisions, P/L, and future outcomes. The batch-construction CLI rejects unexpected window/candle fields rather than quietly carrying extra metadata into the packet.

Every packet is labeled independently for:

- zone present / absent / ambiguous;
- liquidity sweep present / absent / ambiguous;
- structure shift present / absent / ambiguous;
- retest present / absent / ambiguous;
- long / short / none / ambiguous direction.

At least two distinct reviewer identities are required. Agreement finalizes directly. Disagreement requires a third independent adjudicator who cannot be one of the packet reviewers.

The chronological validation boundary is fixed: first `floor(2N/3)` packets are calibration, final one-third are holdout. The partition cannot be tuned by random seed, ratio selection, or best-looking split. The manifest hash binds the exact frozen batch and partition membership.

Example batch creation:

```bash
python scripts/create_technical_annotation_batch.py raw-chart-windows.json \
  --as-of 2026-08-07T20:00:00Z \
  --batch-output technical-annotation-batch.json \
  --manifest-output technical-holdout-manifest.json
```

Example calibration finalization:

```bash
python scripts/finalize_technical_annotations.py \
  technical-annotation-batch.json \
  technical-holdout-manifest.json \
  reviewer-submissions.jsonl \
  --adjudications adjudications.jsonl \
  --partition calibration \
  --output calibration-ground-truth.jsonl
```

The holdout should not be opened for tuning. Acceptance criteria must be chosen from calibration labels first, frozen, and then evaluated once against holdout truth.

## 4. Flow divergence research state machine

`FlowDivergenceResearchPolicy` requires genuine non-local centralized flow. `broker_tick_proxy` and equivalent local spot activity proxies are explicitly ineligible.

The policy progresses through:

- `INELIGIBLE`: centralized flow missing, stale/unusable, low confidence, or no normalized pressure;
- `WATCHING`: valid flow exists but divergence/location conditions are incomplete;
- `ARMED`: opposing price/flow divergence exists at a key location;
- `CONFIRMED`: the armed condition is followed by structure shift.

A bullish example is price declining materially while centralized directional pressure is sufficiently positive. The bearish case is the inverse.

`ResearchFlowSignal.executable` is hard-coded false. This module has no broker client, no risk authorization creation, and no order-submission path.

## 5. Centralized VWAP repositioning research state machine

`VwapRepositioningResearchPolicy` requires:

- genuine centralized flow source;
- sufficient source confidence;
- actual centralized VWAP;
- decisive price repositioning from one side of VWAP to the other beyond the configured pip buffer;
- directional institutional-flow alignment;
- structure shift for final confirmation.

A VWAP cross without aligned flow remains only `ARMED`. Confirmation still has no execution authority.

## 6. Data/evidence still required

The new flow strategy code does not manufacture the underlying evidence. Research remains blocked on real centralized data until an operator supplies CME/equivalent futures/venue inputs, correct contract mapping and roll handling, historical point-in-time archives, and prospective shadow observations.

Likewise, the technical annotation machinery does not create human truth. Independent expert reviewers must actually label the frozen chart packets. Those labels then need agreement/adjudication analysis and calibration/holdout evaluation against the runtime detector.

## 7. OANDA Practice boundary

This release does not change the OANDA endpoint restriction or credential handling. Tokens remain runtime-only. No token, account ID, or vendor payload belongs in source control or campaign policy identity.

The current development date is Saturday, August 8, 2026, when the FX market is closed. Software CI can be completed now, but representative execution evidence should continue only when the market is open and the runtime environment can reach OANDA Practice:

```text
read-only authenticated probe
-> reconciliation
-> all-pair shadow scan
-> protected minimum-size Practice round trip
-> capped Practice campaign
-> mature outcomes and after-cost research
```

## 8. Promotion boundary

No strategy is promoted by this release. Promotion still requires real evidence: after-cost expectancy, drawdown, calibration, attribution/ablation, reproducibility, sufficient sample size across regimes, and sustained authenticated Practice behavior.
