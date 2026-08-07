from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

import pytest

from forex_trader.adapters.readiness_guard import ReconciliationGuardedBroker
from forex_trader.application.sync import BrokerStateSynchronizer
from forex_trader.domain.context import HealthState, ProviderHealth
from forex_trader.domain.enums import DecisionDisposition, Direction, OrderStatus, RiskDisposition
from forex_trader.domain.fusion import RegimeAwareSignalFusionPolicy
from forex_trader.domain.models import (
    AccountSnapshot,
    FundamentalAssessment,
    OrderRequest,
    OrderResult,
    Quote,
    TechnicalAssessment,
    TradeCandidate,
)
from forex_trader.domain.risk_advanced import EnhancedRiskPolicy
from forex_trader.domain.setup import SetupState
from forex_trader.domain.setup_lifecycle import SetupInstance, SetupLifecycleState, SetupTransition
from forex_trader.infrastructure.advanced_repository import AdvancedTradingRepository
from forex_trader.ingestion.providers import UnavailableOrderFlowProvider

NOW = datetime(2026, 8, 6, 14, 0, tzinfo=UTC)


def technical(*, flow: str = "0") -> TechnicalAssessment:
    return TechnicalAssessment(
        instrument="EUR_USD",
        direction=Direction.LONG,
        score=Decimal("0.90"),
        atr=Decimal("0.001"),
        rsi=Decimal("55"),
        entry_reference=Decimal("1.1000"),
        stop_reference=Decimal("1.0950"),
        take_profit_reference=Decimal("1.1100"),
        reasons=("structure",),
        signal_time=NOW,
        liquidity_sweep=True,
        displacement=True,
        trend_strength=Decimal("0.9"),
        setup_family="sweep_reclaim",
        setup_state=SetupState.ENTRY_CONFIRMED.value,
        zone_id="z1",
        zone_quality=Decimal("0.8"),
        liquidity_kind="prior_day_low",
        liquidity_price=Decimal("1.096"),
        liquidity_strength=Decimal("0.8"),
        structure_shift=True,
        retest_confirmed=True,
        location_score=Decimal("0.8"),
        flow_pressure=Decimal(flow),
        flow_source="broker_tick_proxy" if Decimal(flow) != 0 else "none",
    )


def fundamental() -> FundamentalAssessment:
    return FundamentalAssessment("EUR_USD", Decimal("0.2"), Decimal("0"), Decimal("0.2"), Decimal("0.8"), ("macro",))


def test_regime_aware_fusion_enforces_independent_categories() -> None:
    quote = Quote("EUR_USD", Decimal("1.1000"), Decimal("1.1001"), NOW)
    policy = RegimeAwareSignalFusionPolicy(minimum_score=Decimal("0.6"), minimum_independent_confirmations=2, minimum_independent_sources=2)
    candidate = policy.evaluate(technical(), fundamental(), quote)
    assert candidate.disposition is DecisionDisposition.TRADE
    assert candidate.evidence["selected_policy"] == "sweep_reclaim:v1"
    assert candidate.evidence["independent_confirmation_count"] >= 3

    strict = RegimeAwareSignalFusionPolicy(minimum_score=Decimal("0.6"), minimum_independent_confirmations=4, minimum_independent_sources=4)
    rejected = strict.evaluate(technical(), fundamental(), quote)
    assert rejected.disposition is DecisionDisposition.ABSTAIN
    assert rejected.rejection_code == "INDEPENDENT_CONFIRMATION_MISSING"


def candidate() -> TradeCandidate:
    return TradeCandidate(
        candidate_id=__import__("uuid").uuid4(),
        instrument="EUR_USD",
        direction=Direction.LONG,
        disposition=DecisionDisposition.TRADE,
        score=Decimal("0.8"),
        entry_price=Decimal("1.1000"),
        stop_loss=Decimal("1.0950"),
        take_profit=Decimal("1.1100"),
        technical_score=Decimal("0.8"),
        fundamental_score=Decimal("0.6"),
        reasons=(),
        signal_time=NOW,
        execution_key="key",
    )


def test_enhanced_risk_returns_integrity_protected_contract() -> None:
    account = AccountSnapshot("acct", "USD", Decimal("10000"), Decimal("10000"), margin_available=Decimal("9000"))
    quote = Quote("EUR_USD", Decimal("1.0999"), Decimal("1.1001"), NOW)
    policy = EnhancedRiskPolicy(environment="simulation")
    result = policy.authorize(candidate(), account, quote)
    assert result.disposition is RiskDisposition.GRANTED
    assert result.candidate_hash and len(result.candidate_hash) == 64
    assert result.integrity_digest and len(result.integrity_digest) == 64
    assert result.maximum_loss is not None and result.maximum_loss > result.risk_amount
    assert result.required_protection
    assert result.risk_policy_version == "practice-risk-v0.7"


def test_enhanced_risk_denies_drawdown_streak_and_reserved_risk() -> None:
    account = AccountSnapshot("acct", "USD", Decimal("10000"), Decimal("10000"))
    quote = Quote("EUR_USD", Decimal("1.0999"), Decimal("1.1001"), NOW)
    drawdown = EnhancedRiskPolicy(state_provider=lambda _account, _nav: {"drawdown_fraction": Decimal("0.2")})
    assert drawdown.authorize(candidate(), account, quote).disposition is RiskDisposition.DENIED
    streak = EnhancedRiskPolicy(state_provider=lambda _account, _nav: {"drawdown_fraction": 0, "loss_streak": 6})
    assert streak.authorize(candidate(), account, quote).disposition is RiskDisposition.DENIED
    reserved = EnhancedRiskPolicy(state_provider=lambda _account, _nav: {"drawdown_fraction": 0, "loss_streak": 0, "reserved_risk": 200, "pending_risk": 0})
    assert reserved.authorize(candidate(), account, quote).disposition is RiskDisposition.DENIED


def test_advanced_repository_persists_readiness_setup_and_risk_state(tmp_path: Path) -> None:
    repository = AdvancedTradingRepository(tmp_path / "state.db")
    assert not repository.execution_ready("acct")
    repository.set_execution_readiness("acct", True, broker_cursor="10", reason="synced")
    assert repository.execution_ready("acct")
    assert repository.execution_readiness("acct")["broker_cursor"] == "10"

    setup = SetupInstance.create(instrument="EUR_USD", setup_family="sweep_reclaim", policy_version="v1", created_at=NOW, anchor_id="z1")
    repository.save_setup_instance(setup)
    transition = SetupTransition.create(
        setup_id=setup.setup_id,
        from_state=SetupLifecycleState.OBSERVING,
        to_state=SetupLifecycleState.CONTEXT_ELIGIBLE,
        available_at=NOW + timedelta(seconds=1),
        event_id="e1",
        reason="eligible",
    )
    repository.save_setup_transition(transition)
    repository.save_setup_transition(transition)
    assert repository.setup_transitions(setup.setup_id) == [transition]
    repository.save_setup_instance(setup.apply(transition))

    first = repository.update_advanced_risk_state(account_id="acct", nav=Decimal("10000"), realized_loss=True)
    assert first["loss_streak"] == 1
    second = repository.update_advanced_risk_state(account_id="acct", nav=Decimal("9500"), reserved_risk=Decimal("10"), pending_risk=Decimal("5"))
    assert second["drawdown_fraction"] == Decimal("0.05")
    assert repository.advanced_risk_state("acct", Decimal("9500"))["reserved_risk"] == Decimal("10")


class FakeBroker:
    account_id = "acct"

    def __init__(self) -> None:
        self.orders = 0

    def account(self) -> AccountSnapshot:
        return AccountSnapshot("acct", "USD", Decimal("10000"), Decimal("10000"))

    def place_market_order(self, request: OrderRequest) -> OrderResult:
        self.orders += 1
        return OrderResult(request.client_order_id, "1", OrderStatus.FILLED, request.instrument, request.units, request.intended_price)


class FakeSource(FakeBroker):
    def last_transaction_id(self) -> str:
        return "10"

    def transactions_since(self, transaction_id: str) -> tuple[list[dict[str, object]], str]:
        assert transaction_id == "10"
        return ([{"id": "11", "type": "ORDER"}], "11")

    def transactions_between(self, _start: datetime, _end: datetime) -> list[dict[str, object]]:
        return []


def request() -> OrderRequest:
    return OrderRequest("client", "EUR_USD", Direction.LONG, 10, Decimal("1.09"), Decimal("1.11"), intended_price=Decimal("1.10"))


def test_reconciliation_guard_blocks_until_sync_marks_durable_readiness(tmp_path: Path) -> None:
    repository = AdvancedTradingRepository(tmp_path / "guard.db")
    broker = FakeSource()
    guarded = ReconciliationGuardedBroker(broker, repository)
    with pytest.raises(RuntimeError, match="run forex-trader sync"):
        guarded.place_market_order(request())
    synchronizer = BrokerStateSynchronizer(guarded, repository)
    assert synchronizer.catch_up() == 1
    assert repository.execution_ready("acct")
    result = guarded.place_market_order(request())
    assert result.status is OrderStatus.FILLED
    assert broker.orders == 1


def test_unavailable_flow_provider_never_fabricates_snapshot() -> None:
    health = ProviderHealth("institutional-flow", HealthState.UNAVAILABLE, NOW, detail="not licensed")
    provider = UnavailableOrderFlowProvider(health)
    assert provider.snapshot("EUR_USD", as_of=NOW) is None
    assert provider.health() is health
