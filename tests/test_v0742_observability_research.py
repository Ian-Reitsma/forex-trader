from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from types import SimpleNamespace
from uuid import uuid4

import pytest

from forex_trader.application.runtime_diagnostics import (
    basic_readiness_contract,
    breaker_snapshot,
    eligibility_layers,
    provider_snapshot,
)
from forex_trader.domain.context import HealthState, ProviderHealth
from forex_trader.domain.enums import DecisionDisposition, Direction
from forex_trader.domain.events import ScheduledMacroEvent
from forex_trader.domain.models import AccountSnapshot, Candle, TradeCandidate
from forex_trader.domain.position_management import RuntimeManagementPolicy
from forex_trader.domain.risk_advanced import EnhancedRiskPolicy
from forex_trader.infrastructure.advanced_repository import AdvancedTradingRepository
from forex_trader.research.backtest import OutcomeStatus
from forex_trader.research.runtime_management_shadow import evaluate_runtime_management_shadow


class _MarketProvider:
    def quote(self) -> None:
        return None

    def candles(self) -> None:
        return None

    def candles_between(self) -> None:
        return None

    def instrument_spec(self) -> None:
        return None


class _MarketWrapper:
    def __init__(self, observed_at: datetime) -> None:
        self.provider = _MarketProvider()
        self.observed_at = observed_at

    def health(self) -> ProviderHealth:
        return ProviderHealth("fixture-market", HealthState.HEALTHY, self.observed_at)


class _Broker:
    def account(self) -> None:
        return None

    def positions(self) -> None:
        return None

    def place_order(self) -> None:
        return None

    def transactions_since(self) -> None:
        return None

    def transaction_stream(self) -> None:
        return None

    def instrument_spec(self) -> None:
        return None


def test_provider_snapshot_is_secret_free_capability_observability() -> None:
    now = datetime(2026, 8, 12, tzinfo=UTC)
    engine = SimpleNamespace(market_data=_MarketWrapper(now), broker=_Broker())
    snapshot = provider_snapshot(engine)
    assert snapshot["schema"] == "provider-capability-snapshot-v1"
    assert snapshot["market_data"]["health"]["state"] == "healthy"  # type: ignore[index]
    assert snapshot["market_data"]["capabilities"]["quote"] is True  # type: ignore[index]
    assert snapshot["broker"]["capabilities"]["place_order"] is True  # type: ignore[index]
    assert "token" not in str(snapshot).lower()


def test_provider_snapshot_handles_provider_without_explicit_health_contract() -> None:
    snapshot = provider_snapshot(SimpleNamespace(market_data=_MarketProvider(), broker=_Broker()))
    assert snapshot["market_data"]["wrapper"] == "_MarketProvider"  # type: ignore[index]
    assert snapshot["market_data"]["health"] is None  # type: ignore[index]
    assert snapshot["environment"] == "local_or_simulated"


def test_basic_readiness_contract_does_not_claim_full_trade_readiness() -> None:
    contract = basic_readiness_contract()
    assert contract["scope"] == "market_data_and_reconciliation"
    assert contract["requirements"]["fundamentals"] is False  # type: ignore[index]
    assert "not equivalent" in str(contract["interpretation"])


def test_eligibility_layers_separate_preflight_calendar_and_final_decision() -> None:
    now = datetime(2026, 8, 12, tzinfo=UTC)
    engine = SimpleNamespace(
        fusion_policy=SimpleNamespace(require_fundamentals=True, minimum_fundamental_confidence=Decimal("0.50")),
        fundamentals=SimpleNamespace(
            assess_pair=lambda instrument, as_of: SimpleNamespace(confidence=Decimal("0.75"), reasons=("covered",))
        ),
        risk_policy=SimpleNamespace(
            macro_factor_guard=SimpleNamespace(
                require_classification=True,
                factor_map={"AUD_CHF": frozenset({"macro:AUD", "macro:CHF"})},
            )
        ),
        repository=SimpleNamespace(scheduled_events=lambda **kwargs: []),
    )
    layers = eligibility_layers(engine, "aud_chf", observed_at=now)
    assert layers["fundamental_preflight"]["eligible"] is True  # type: ignore[index]
    assert layers["macro_factor"]["classified"] is True  # type: ignore[index]
    assert layers["calendar"]["state"] == "empty"  # type: ignore[index]
    assert layers["final_trade_eligible"] is None
    assert layers["risk_breaker"]["included"] is False  # type: ignore[index]


def test_eligibility_layers_reports_populated_pair_calendar() -> None:
    now = datetime(2026, 8, 12, tzinfo=UTC)
    event = ScheduledMacroEvent.create(currency="USD", scheduled_at=now + timedelta(hours=2), name="official release")
    engine = SimpleNamespace(
        fusion_policy=SimpleNamespace(require_fundamentals=False, minimum_fundamental_confidence=Decimal("0.50")),
        fundamentals=SimpleNamespace(
            assess_pair=lambda instrument, as_of: SimpleNamespace(confidence=Decimal("0"), reasons=("not required",))
        ),
        risk_policy=SimpleNamespace(macro_factor_guard=None),
        repository=SimpleNamespace(scheduled_events=lambda **kwargs: [event]),
    )
    layers = eligibility_layers(engine, "EUR_USD", observed_at=now)
    assert layers["fundamental_preflight"]["eligible"] is True  # type: ignore[index]
    assert layers["macro_factor"]["classified"] is True  # type: ignore[index]
    assert layers["calendar"]["state"] == "populated"  # type: ignore[index]
    assert layers["calendar"]["relevant_events_next_24h"] == 1  # type: ignore[index]


def test_eligibility_layers_reports_unsupported_calendar() -> None:
    now = datetime(2026, 8, 12, tzinfo=UTC)
    engine = SimpleNamespace(
        fusion_policy=SimpleNamespace(require_fundamentals=False, minimum_fundamental_confidence=Decimal("0.50")),
        fundamentals=SimpleNamespace(
            assess_pair=lambda instrument, as_of: SimpleNamespace(confidence=Decimal("0"), reasons=())
        ),
        risk_policy=SimpleNamespace(macro_factor_guard=None),
        repository=SimpleNamespace(),
    )
    layers = eligibility_layers(engine, "EUR_USD", observed_at=now)
    assert layers["calendar"]["state"] == "unsupported"  # type: ignore[index]


def test_eligibility_layers_reject_malformed_pair() -> None:
    with pytest.raises(ValueError, match="normalized FX pair"):
        eligibility_layers(SimpleNamespace(), "EURUSD")


def test_breaker_snapshot_reports_not_applicable_for_basic_policy() -> None:
    engine = SimpleNamespace(risk_policy=SimpleNamespace())
    assert breaker_snapshot(engine)["state"] == "not_applicable"


def test_breaker_snapshot_reports_enhanced_policy_account_failure() -> None:
    class BrokenBroker:
        def account(self) -> None:
            raise RuntimeError("broker unavailable")

    snapshot = breaker_snapshot(SimpleNamespace(risk_policy=EnhancedRiskPolicy(), broker=BrokenBroker()))
    assert snapshot["supported"] is True
    assert snapshot["state"] == "account_unavailable"
    assert "broker unavailable" in str(snapshot["reason"])


def test_breaker_snapshot_reads_durable_enhanced_risk_state() -> None:
    repository = AdvancedTradingRepository(":memory:")
    account = AccountSnapshot("practice-account", "USD", Decimal("100000"), Decimal("100000"))
    engine = SimpleNamespace(
        risk_policy=EnhancedRiskPolicy(max_loss_streak=6),
        broker=SimpleNamespace(account=lambda: account),
        repository=repository,
    )
    snapshot = breaker_snapshot(engine)
    assert snapshot["supported"] is True
    assert snapshot["account_id"] == "practice-account"
    assert snapshot["loss_streak"] == 0
    assert snapshot["maximum_loss_streak"] == 6
    assert snapshot["blocked"] is False


def _candidate(signal_time: datetime, direction: Direction = Direction.LONG) -> TradeCandidate:
    if direction is Direction.LONG:
        stop, target = Decimal("0.9900"), Decimal("1.0200")
    else:
        stop, target = Decimal("1.0100"), Decimal("0.9800")
    return TradeCandidate(
        candidate_id=uuid4(),
        instrument="EUR_USD",
        direction=direction,
        disposition=DecisionDisposition.TRADE,
        score=Decimal("0.82"),
        entry_price=Decimal("1.0000"),
        stop_loss=stop,
        take_profit=target,
        technical_score=Decimal("0.8"),
        fundamental_score=Decimal("0.2"),
        reasons=(),
        signal_time=signal_time,
    )


def _flat_candles(start: datetime, count: int, close: Decimal) -> list[Candle]:
    return [
        Candle(
            time=start + timedelta(minutes=5 * index),
            open=close,
            high=close + Decimal("0.0005"),
            low=close - Decimal("0.0005"),
            close=close,
            volume=100,
            complete=True,
        )
        for index in range(count)
    ]


def test_runtime_management_shadow_closes_failure_to_progress_at_thirty_minutes() -> None:
    start = datetime(2026, 8, 12, 12, tzinfo=UTC)
    trade = evaluate_runtime_management_shadow(_candidate(start), _flat_candles(start, 12, Decimal("1.0005")))
    assert trade.bars_held == 6
    assert "failure to progress" in trade.exit_reason
    assert trade.r_multiple == Decimal("0.05")


def test_runtime_management_shadow_enforces_two_hour_maximum_holding_time() -> None:
    start = datetime(2026, 8, 12, 12, tzinfo=UTC)
    trade = evaluate_runtime_management_shadow(_candidate(start), _flat_candles(start, 30, Decimal("1.0020")))
    assert trade.bars_held == 24
    assert "maximum scalp holding time" in trade.exit_reason
    assert trade.r_multiple == Decimal("0.2")


def test_runtime_management_shadow_target_and_same_bar_stop_first() -> None:
    start = datetime(2026, 8, 12, 12, tzinfo=UTC)
    target_only = Candle(start, Decimal("1.0000"), Decimal("1.0210"), Decimal("0.9990"), Decimal("1.0150"))
    winner = evaluate_runtime_management_shadow(_candidate(start), [target_only])
    assert winner.status is OutcomeStatus.WIN
    assert winner.exit_reason == "shadow_target"
    assert winner.r_multiple == Decimal("2")

    ambiguous = Candle(start, Decimal("1.0000"), Decimal("1.0210"), Decimal("0.9890"), Decimal("1.0000"))
    stopped = evaluate_runtime_management_shadow(_candidate(start), [ambiguous])
    assert stopped.status is OutcomeStatus.LOSS
    assert stopped.ambiguous_bar is True
    assert stopped.exit_reason == "shadow_stop"


def test_runtime_management_shadow_short_target_and_stop_paths() -> None:
    start = datetime(2026, 8, 12, 12, tzinfo=UTC)
    target = Candle(start, Decimal("1.0000"), Decimal("1.0010"), Decimal("0.9790"), Decimal("0.9850"))
    winner = evaluate_runtime_management_shadow(_candidate(start, Direction.SHORT), [target])
    assert winner.status is OutcomeStatus.WIN
    assert winner.r_multiple == Decimal("2")

    stop = Candle(start, Decimal("1.0000"), Decimal("1.0110"), Decimal("0.9990"), Decimal("1.0050"))
    loser = evaluate_runtime_management_shadow(_candidate(start, Direction.SHORT), [stop])
    assert loser.status is OutcomeStatus.LOSS
    assert loser.exit_reason == "shadow_stop"


def test_runtime_management_shadow_break_even_stop_is_not_mislabeled_loss() -> None:
    start = datetime(2026, 8, 12, 12, tzinfo=UTC)
    first = Candle(start, Decimal("1.0000"), Decimal("1.0110"), Decimal("0.9995"), Decimal("1.0110"))
    second = Candle(start + timedelta(minutes=5), Decimal("1.0050"), Decimal("1.0060"), Decimal("0.9990"), Decimal("1.0010"))
    trade = evaluate_runtime_management_shadow(_candidate(start), [first, second])
    assert trade.exit_reason == "shadow_stop"
    assert trade.r_multiple == Decimal("0")
    assert trade.status is OutcomeStatus.TIMEOUT


def test_runtime_management_shadow_observation_horizon_and_validation() -> None:
    start = datetime(2026, 8, 12, 12, tzinfo=UTC)
    policy = RuntimeManagementPolicy(
        maximum_holding_time=timedelta(hours=10),
        progress_check_after=timedelta(hours=9),
    )
    trade = evaluate_runtime_management_shadow(
        _candidate(start),
        _flat_candles(start, 3, Decimal("1.0050")),
        policy,
    )
    assert trade.status is OutcomeStatus.TIMEOUT
    assert trade.exit_reason == "shadow_observation_horizon_ended"
    assert trade.bars_held == 3

    with pytest.raises(ValueError, match="tradeable"):
        evaluate_runtime_management_shadow(replace(_candidate(start), disposition=DecisionDisposition.ABSTAIN), [trade_candle(start)])
    with pytest.raises(ValueError, match="execution costs"):
        evaluate_runtime_management_shadow(_candidate(start), [trade_candle(start)], spread_pips=Decimal("-1"))
    with pytest.raises(ValueError, match="completed future candle"):
        evaluate_runtime_management_shadow(_candidate(start), [])


def trade_candle(start: datetime) -> Candle:
    return Candle(start, Decimal("1.0000"), Decimal("1.0010"), Decimal("0.9990"), Decimal("1.0000"))
