from __future__ import annotations

from forex_trader.domain.context import (
    FlowRequirement,
    MarketRegime,
    PolicyAuthority,
    StrategyPolicy,
    StrategyPolicyRegistry,
    default_strategy_policies,
)


def audited_strategy_policies() -> tuple[StrategyPolicy, ...]:
    """Complete strategy catalogue from the audited blueprint.

    Newly added families remain research-only. Presence in this registry is not
    execution authority and cannot promote them above the existing sweep/reclaim policy.
    """

    return (
        *default_strategy_policies(),
        StrategyPolicy(
            "flow_divergence",
            "v1",
            frozenset({MarketRegime.RANGE, MarketRegime.TRANSITION, MarketRegime.POST_EVENT_NORMALIZED}),
            PolicyAuthority.RESEARCH,
            FlowRequirement.REQUIRED,
            3,
        ),
        StrategyPolicy(
            "vwap_repositioning",
            "v1",
            frozenset({MarketRegime.TREND, MarketRegime.TRANSITION, MarketRegime.POST_EVENT_NORMALIZED}),
            PolicyAuthority.RESEARCH,
            FlowRequirement.REQUIRED,
            3,
        ),
    )


class CompleteStrategyPolicyRegistry(StrategyPolicyRegistry):
    def __init__(self) -> None:
        super().__init__(audited_strategy_policies())
