import json
from types import SimpleNamespace

import pytest

from forex_trader.application.campaign import PracticeCampaignRunner
from forex_trader.domain.enums import DecisionDisposition, OrderStatus, RiskDisposition


class FakeEngine:
    def __init__(self, plan):  # type: ignore[no-untyped-def]
        self.plan = plan
        self.calls: list[tuple[str, bool]] = []

    def evaluate(self, instrument: str, *, execute: bool = False):  # type: ignore[no-untyped-def]
        self.calls.append((instrument, execute))
        action = self.plan[instrument]
        if action == "error":
            raise RuntimeError("synthetic provider failure")
        if action == "abstain":
            return SimpleNamespace(
                candidate=SimpleNamespace(
                    disposition=DecisionDisposition.ABSTAIN,
                    rejection_code="NO_STRUCTURE_SHIFT",
                ),
                risk=None,
                order=None,
            )
        if action == "risk-denied":
            return SimpleNamespace(
                candidate=SimpleNamespace(
                    disposition=DecisionDisposition.TRADE,
                    rejection_code=None,
                ),
                risk=SimpleNamespace(
                    disposition=RiskDisposition.DENIED,
                    reasons=("correlation risk veto",),
                ),
                order=None,
            )

        order = None
        if execute:
            status = {
                "protected": OrderStatus.PROTECTED,
                "filled": OrderStatus.FILLED,
                "rejected": OrderStatus.REJECTED,
                "unknown": OrderStatus.UNKNOWN,
            }[action]
            order = SimpleNamespace(status=status)
        return SimpleNamespace(
            candidate=SimpleNamespace(
                disposition=DecisionDisposition.TRADE,
                rejection_code=None,
            ),
            risk=SimpleNamespace(
                disposition=RiskDisposition.GRANTED,
                reasons=("authorized",),
            ),
            order=order,
        )

    def promotion_status(self):  # type: ignore[no-untyped-def]
        return {"ready": False}


def test_campaign_keeps_evaluating_in_shadow_after_order_budget_is_spent(tmp_path) -> None:
    engine = FakeEngine(
        {
            "EUR_USD": "protected",
            "GBP_USD": "filled",
            "USD_JPY": "abstain",
        }
    )
    evidence = tmp_path / "campaign.jsonl"
    runner = PracticeCampaignRunner(
        engine,  # type: ignore[arg-type]
        ["eur_usd", "GBP_USD", "USD_JPY", "EUR_USD"],
        execute=True,
        max_new_orders_per_cycle=1,
        evidence_path=evidence,
    )
    report = runner.run_cycle(1)
    assert engine.calls == [
        ("EUR_USD", True),
        ("GBP_USD", False),
        ("USD_JPY", False),
    ]
    assert report.instruments_requested == 3
    assert report.instruments_evaluated == 3
    assert report.trade_candidates == 2
    assert report.abstentions == 1
    assert report.orders_submitted == 1
    assert report.orders_protected == 1
    assert report.rejection_codes == {"NO_STRUCTURE_SHIFT": 1}
    payload = json.loads(evidence.read_text().strip())
    assert payload["orders_submitted"] == 1
    assert payload["promotion_ready"] is False


def test_unknown_broker_state_stops_remaining_cycle_immediately() -> None:
    engine = FakeEngine({"EUR_USD": "unknown", "GBP_USD": "protected"})
    runner = PracticeCampaignRunner(
        engine,  # type: ignore[arg-type]
        ["EUR_USD", "GBP_USD"],
        execute=True,
        max_new_orders_per_cycle=2,
    )
    report = runner.run_cycle()
    assert engine.calls == [("EUR_USD", True)]
    assert report.orders_unknown == 1
    assert report.stopped_early is True
    assert "UNKNOWN" in str(report.stop_reason)


def test_campaign_records_risk_denials_and_provider_errors_without_lowering_gates() -> None:
    engine = FakeEngine(
        {
            "EUR_USD": "risk-denied",
            "GBP_USD": "error",
            "USD_JPY": "abstain",
        }
    )
    runner = PracticeCampaignRunner(
        engine,  # type: ignore[arg-type]
        ["EUR_USD", "GBP_USD", "USD_JPY"],
        execute=False,
        max_new_orders_per_cycle=0,
    )
    report = runner.run_cycle()
    assert report.risk_denials == 1
    assert report.risk_denial_reasons == {"correlation risk veto": 1}
    assert report.errors == 1
    assert report.error_types == {"RuntimeError": 1}
    assert report.orders_submitted == 0


def test_campaign_run_sleeps_between_cycles_and_aggregates() -> None:
    engine = FakeEngine({"EUR_USD": "abstain"})
    sleeps: list[float] = []
    seen: list[int] = []
    runner = PracticeCampaignRunner(
        engine,  # type: ignore[arg-type]
        ["EUR_USD"],
        execute=False,
    )
    report = runner.run(
        max_cycles=3,
        interval_seconds=2.5,
        sleeper=sleeps.append,
        on_cycle=lambda cycle: seen.append(cycle.cycle),
    )
    assert len(report.cycles) == 3
    assert report.evaluated == 3
    assert report.submitted == 0
    assert report.unknown == 0
    assert sleeps == [2.5, 2.5]
    assert seen == [1, 2, 3]


def test_campaign_run_stops_future_cycles_after_unknown() -> None:
    engine = FakeEngine({"EUR_USD": "unknown"})
    runner = PracticeCampaignRunner(
        engine,  # type: ignore[arg-type]
        ["EUR_USD"],
        execute=True,
    )
    report = runner.run(max_cycles=4, interval_seconds=0)
    assert len(report.cycles) == 1
    assert report.unknown == 1


def test_campaign_validates_operator_limits() -> None:
    engine = FakeEngine({"EUR_USD": "abstain"})
    with pytest.raises(ValueError, match="at least one instrument"):
        PracticeCampaignRunner(engine, [], execute=False)  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="cannot be negative"):
        PracticeCampaignRunner(  # type: ignore[arg-type]
            engine, ["EUR_USD"], execute=False, max_new_orders_per_cycle=-1
        )
    runner = PracticeCampaignRunner(engine, ["EUR_USD"], execute=False)  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="cycle number"):
        runner.run_cycle(0)
    with pytest.raises(ValueError, match="max_cycles"):
        runner.run(max_cycles=0, interval_seconds=0)
    with pytest.raises(ValueError, match="interval_seconds"):
        runner.run(max_cycles=1, interval_seconds=-1)
