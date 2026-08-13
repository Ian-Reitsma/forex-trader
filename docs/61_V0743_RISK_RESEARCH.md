# v0.7.43 Risk Research Findings

This release documents the post-v0.7.42 forward Practice evidence and adds read-only research helpers. It does not increase broker authority, order size, risk fraction, or live-money capability.

## Forward evidence

The morning 2026-08-13 diagnostic showed 9 closed strategy trades, 0 wins, total realized P/L of -633.0883 USD, and a post-review realized strategy loss streak of 3. Runtime health, OANDA Practice transport, reconciliation, provider health, and protection placement were healthy.

## Position sizing diagnosis

The configured policy uses a per-trade risk fraction of 0.0015 of the smaller of balance or NAV. A separate configured maximum of 100,000 units can bind before the risk-at-stop budget is fully consumed. Margin used must not be interpreted as position notional; leveraged FX positions can control substantially more notional than the displayed margin requirement.

The correct research question is therefore whether a granted trade is using its intended risk-at-stop budget, not whether the margin-used number appears small. The new `research.capital_utilization` helper quantifies authorized risk utilization, raw risk-budget units, configured/broker unit constraints, quote-currency notional, and estimated quote-currency margin from durable decision traces.

## Management replay result

The post-overnight position-management shadow contained 8 executed/protected candidates. Static bracket management produced -8.139336030113859643435796209R with 0 wins and 8 losses. The existing RuntimeManagementPolicy produced -1.982948841641203075762926718R, 2 wins and 6 losses, for a +6.156387188472656567672869491R delta. Maximum drawdown improved from 8.139336030113859643435796209R to 2.066282174974536409096260051R.

Every one of the 8 replayed trades had a positive delta-R under the management policy. The policy remains research-only and broker_write_authority remains false. Eight observations are not sufficient evidence to grant new broker-side close/modify authority, but the consistency is strong enough to make prospective management-shadow validation the highest-priority next experiment.

## Execution review threshold

`application.practice_execution_guard` provides a read-only assessment that recommends operator review when the durable realized strategy loss streak reaches 3. It does not alter the broker, risk authorization, order count, or autonomous runtime. This is intentionally separate from the existing authoritative loss breaker.

## Acceptance direction

Do not increase the configured risk fraction based on margin-used screenshots or a single favorable unrealized excursion. First establish positive forward expectancy and prospectively validate management decisions. If future sizing work removes an arbitrary unit bottleneck, risk-at-stop, broker maximum position size, margin reserve, gross/currency exposure, macro-factor concentration, drawdown, and loss-streak controls must remain authoritative.
