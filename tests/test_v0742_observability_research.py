from __future__ import annotations

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
from forex_trader.domain.models import Candle, TradeCandidate
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


def test_eligibility_layers_reject_malformed_pair() -> None:
    with pytest.raises(ValueError, match="normalized FX pair"):
        eligibility_layers(SimpleNamespace(), "EURUSD")


def test_breaker_snapshot_reports_not_applicable_for_basic_policy() -> None:
    engine = SimpleNamespace(risk_policy=SimpleNamespace())
    assert breaker_snapshot(engine)["state"] == "not_applicable"


def _candidate(signal_time: datetime) -> TradeCandidate:
    return TradeCandidate(
        candidate_id=uuid4(),
        instrument="EUR_USD",
        direction=Direction.LONG,
        disposition=DecisionDisposition.TRADE,
        score=Decimal("0.82"),
        entry_price=Decimal("1.0000"),
        stop_loss=Decimal("0.9900"),
        take_profit=Decimal("1.0200"),
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
